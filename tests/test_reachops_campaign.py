import csv
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
import zipfile
from collections import Counter
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from unittest.mock import patch

from ReachOps.adapters.browser_manager import WorkbenchBrowserAdapter
from ReachOps.adapters.ix_profile_group_manager import IxProfileGroupManager, ProfileGroupMoveResult
from ReachOps import PRODUCT_ID, PRODUCT_NAME, VERSION, ReachOpsUpdateManager, version_info
from ReachOps.intelligence import GrowthIntelligenceService, GrowthTaskConfig
from ReachOps.intelligence.ai_strategy import HTTPAcquisitionIntelligenceProvider
from ReachOps.intelligence.candidate_user_scorer import CandidateUserScorer
from ReachOps.intelligence.comment_intent import CommentIntentResult, RuleBasedCommentIntentClassifier
from ReachOps.intelligence.growth_task_router import GrowthTaskRouter
from ReachOps.intelligence.operation_lead_manager import OperationLeadManager
from ReachOps.intelligence.outreach_copy import OutreachCopySuggestion
from ReachOps.intelligence.schemas import ActionQueueItem, CampaignFunnel, CandidateUser, DiscoveredContent, DiscoveredCreator
from ReachOps.intelligence.source_planner import CampaignAnalyzer
from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.runtime_paths import RuntimePaths
from ReachOps.workbench.action_router import ActionRouterConfig
from ReachOps.workbench.action_router import FixtureActionExecutor
from ReachOps.workbench.profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig
from ReachOps.workbench.console import GrowthOpsConsole, format_campaign_plan_summary, quick_send_mode_key, quick_send_preset
from ReachOps.workbench.console import group_name_from_display as console_group_name_from_display
from ReachOps.workbench.console import safe_tk_option as console_safe_tk_option
from ReachOps.workbench.standalone_app import GrowthIntelligenceStandaloneApp, group_display_name, group_name_from_display, stable_combobox_values
from ReachOps.workbench.tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor
from ReachOps.workbench.workflow_service import GrowthWorkflowService
from ReachOps.workbench.risk_gate import RiskGate
from tools.reachops_action_preflight_existing_batch import run_preflight as run_reachops_action_preflight_existing_batch
from ReachOps.collectors.normalizer import is_comment_noise_text
from ReachOps.collectors.collector_runtime import CollectorRuntime
from ReachOps.collectors.base import CollectorEvidence
from ReachOps.collectors.tiktok_comment_collector import TikTokCommentCollector
from ReachOps.collectors.tiktok_search_collector import TikTokSearchCollector
from ReachOps.collectors.tiktok_topic_content_collector import TikTokTopicContentCollector
from tools.reachops_delivery_audit import run_audit as run_reachops_delivery_audit
from tools.reachops_activation_status_check import check_activation_status as check_reachops_activation_status
from tools.reachops_activation_status_template import build_template as build_reachops_activation_status_template
from tools.init_reachops_acceptance_inputs import build_content as build_reachops_acceptance_inputs_content
from tools.init_reachops_acceptance_inputs import main as init_reachops_acceptance_inputs_main
from tools.reachops_goal_status_report import build_goal_status_report
from tools.reachops_goal_status_report import main as reachops_goal_status_main
from tools.reachops_operator_pressure import run_pressure as run_reachops_operator_pressure
from tools.reachops_visual_collection_preflight import build_operator_diagnosis as visual_preflight_operator_diagnosis
from tools.reachops_visual_collection_preflight import source_from_plan as visual_preflight_source_from_plan
from tools.reachops_live_validation_manifest import build_manifest as build_reachops_live_validation_manifest
from tools.reachops_live_validation_manifest import load_profile_snapshot as load_reachops_profile_snapshot
from tools.reachops_live_acceptance_status import build_status as build_reachops_live_acceptance_status
from tools.reachops_live_acceptance_status import render_markdown_report as render_reachops_live_acceptance_report
from tools.reachops_live_acceptance_status import write_json_report as write_reachops_live_acceptance_json_report
from tools.reachops_live_acceptance_status import write_markdown_report as write_reachops_live_acceptance_report
from tools.reachops_authorization_handoff_bundle import build_handoff_bundle as build_reachops_authorization_handoff_bundle
from tools.reachops_authorization_handoff_bundle import verify_handoff_bundle as verify_reachops_authorization_handoff_bundle
from tools.reachops_live_preflight import build_environment_diagnostics as build_reachops_live_preflight_environment_diagnostics
from tools.reachops_live_preflight import run_preflight as run_reachops_live_preflight
from tools.reachops_live_readiness import run_readiness as run_reachops_live_readiness
from tools.reachops_live_submit_acceptance import run_acceptance as run_reachops_live_submit_acceptance
from tools.reachops_live_environment_blocker_report import build_report as build_reachops_live_environment_blocker_report
from tools.reachops_live_environment_blocker_report import main as reachops_live_environment_blocker_main
from tools.reachops_ixbrowser_profile_metadata_report import build_report as build_ixbrowser_profile_metadata_report
from tools.verify_reachops_acceptance_summary import verify_summary as verify_reachops_acceptance_summary
from tools.reachops_delivery_package_check import check_delivery_package as check_reachops_delivery_package
from tools.reachops_release_evidence import build_release_evidence as build_reachops_release_evidence
from tools.reachops_ci_release_baseline_audit import build_report as build_reachops_ci_release_baseline_report
from tools.reachops_account_readiness_audit import build_report as build_reachops_account_readiness_report
from tools.reachops_control_plane_audit import build_report as build_reachops_control_plane_report
from tools.reachops_issue_closure_audit import build_report as build_reachops_issue_closure_report
from tools.reachops_data_governance import build_report as build_reachops_data_governance_report
from tools.reachops_security_supply_chain_audit import build_report as build_reachops_security_supply_chain_report
from tools.reachops_start_contract_audit import build_report as build_reachops_start_contract_report
from tools.reachops_outcome_metrics import (
    build_report as build_reachops_outcome_metrics_report,
    import_outcomes_csv as import_reachops_outcomes_csv,
    import_outcomes_webhook_payload as import_reachops_outcomes_webhook_payload,
)
from tools.reachops_final_acceptance_gate import build_final_acceptance_gate as build_reachops_final_acceptance_gate
from tools.reachops_final_acceptance_gate import client_delivery_from_acceptance_summary as reachops_client_delivery_from_acceptance_summary
from tools.reachops_final_acceptance_gate import main as reachops_final_acceptance_gate_main
from tools.reachops_goal_delivery_runner import build_report as build_reachops_goal_delivery_report
from tools.reachops_goal_delivery_runner import build_delivery_boundary as build_reachops_delivery_boundary
from tools.reachops_goal_delivery_runner import build_deliverable_index as build_reachops_deliverable_index
from tools.reachops_goal_delivery_runner import render_markdown_summary as render_reachops_goal_delivery_summary
from tools.reachops_repository_cleanliness_check import scan_repository_cleanliness
from tools.reachops_windows_package_preflight import build_preflight as build_reachops_windows_package_preflight
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


class LoginDialogDriver(FakeDriver):
    def execute_script(self, script):
        text = str(script or "")
        if "const text = String(document.body ? document.body.innerText" in text and "loginDialog" in text:
            return {
                "url": self.current_url,
                "text": "creator video grid",
                "title": "Creator | TikTok",
                "videoLinks": 8,
                "profileLinks": 4,
                "loginDialog": True,
                "exactLoginButton": True,
                "forcedLoginText": False,
                "loginPage": False,
                "captcha": False,
                "proxy": False,
            }
        if "document.readyState" in text:
            return "complete"
        if "querySelectorAll" in text:
            return 8
        return {"dismissed": 0, "labels": []}


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


class FailingCollector:
    def collect(self, driver, task, context):
        raise AssertionError("collector should not run after login dialog is detected")


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


class EmptyCommentCollector:
    def collect(self, driver, task, context):
        return []


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


class EmptyMismatchedUrlCommentCollector:
    level = "selenium_dom"

    def collect(self, driver, task, context):
        return []

    def evidence(self, driver, item_count=0, raw_sample=""):
        return CollectorEvidence(
            level=self.level,
            final_url="https://www.tiktok.com/@other_creator/video/999",
            item_count=item_count,
            raw_sample=raw_sample,
            adapter_name=self.__class__.__name__,
            diagnostics={
                "stop_reason": "url_mismatch",
                "final_url": "https://www.tiktok.com/@other_creator/video/999",
            },
        )


class SameCreatorOtherVideoCommentCollector:
    level = "selenium_dom"

    def __init__(self):
        self.calls = 0

    def collect(self, driver, task, context):
        self.calls += 1
        return [
            {
                "username": "same_creator_wrong_video_user",
                "profile_url": "https://www.tiktok.com/@same_creator_wrong_video_user",
                "comment_text": "where can I buy this",
                "comment_likes": 1,
                "reply_count": 0,
            }
        ]

    def evidence(self, driver, item_count=0, raw_sample=""):
        final_url = "https://www.tiktok.com/@creator/video/999"
        if self.calls > 1:
            final_url = "https://www.tiktok.com/@creator/video/123"
        return CollectorEvidence(
            level=self.level,
            final_url=final_url,
            item_count=item_count,
            raw_sample=raw_sample,
            adapter_name=self.__class__.__name__,
        )


class RecoveringUrlCommentCollector:
    level = "selenium_dom"

    def __init__(self):
        self.calls = 0

    def collect(self, driver, task, context):
        self.calls += 1
        return [
            {
                "username": "target_video_user",
                "profile_url": "https://www.tiktok.com/@target_video_user",
                "comment_text": "where can I buy this",
                "comment_likes": 1,
                "reply_count": 0,
            }
        ]

    def evidence(self, driver, item_count=0, raw_sample=""):
        final_url = "https://www.tiktok.com/@other_creator/video/999" if self.calls == 1 else driver.current_url
        return CollectorEvidence(
            level=self.level,
            final_url=final_url,
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


def minimal_windows_pe_bytes(payload: bytes = b"reachops") -> bytes:
    header_offset = 0x80
    data = bytearray(b"MZ" + b"\x00" * (header_offset + 4 - 2))
    data[0x3C:0x40] = header_offset.to_bytes(4, "little")
    data[header_offset:header_offset + 4] = b"PE\x00\x00"
    data.extend(payload)
    return bytes(data)


def final_package_check_payload():
    artifact_size = len(minimal_windows_pe_bytes())
    return {
        "status": "passed",
        "passed": True,
        "final_delivery_ready": True,
        "bootstrap_only": False,
        "missing_artifacts": [],
        "failures": [],
        "pending_external_validation": [],
        "artifacts": {
            "exe": {
                "exists": True,
                "size": artifact_size,
                "pe_dos_signature_valid": True,
                "pe_header_offset": 128,
                "pe_header_signature_valid": True,
                "pe_signature_valid": True,
            },
            "installer": {
                "exists": True,
                "size": artifact_size,
                "pe_dos_signature_valid": True,
                "pe_header_offset": 128,
                "pe_header_signature_valid": True,
                "pe_signature_valid": True,
            },
            "manifest": {
                "exists": True,
                "size": 1,
                "expected_sha256": "a" * 64,
                "actual_sha256": "a" * 64,
                "expected_size": 12,
                "actual_size": 12,
            },
            "acceptance_summary": {"exists": True, "size": 1},
        },
        "report_files": {
            "delivery_audit": {"exists": True, "size": 1},
            "operator_pressure": {"exists": True, "size": 1},
            "installer_smoke": {"exists": True, "size": 1},
            "ui_startup": {"exists": True, "size": 1},
            "activation_status": {"exists": True, "size": 1},
            "live_acceptance_status": {"exists": True, "size": 1},
            "authorization_handoff": {"exists": True, "size": 1},
            "live_validation": {"exists": True, "size": 1},
            "repository_cleanliness": {"exists": True, "size": 1},
            "windows_package_preflight": {"exists": True, "size": 1},
            "client_delivery": {"exists": True, "size": 1},
            "live_readiness": {"exists": True, "size": 1},
            "live_preflight": {"exists": True, "size": 1},
            "goal_status": {"exists": True, "size": 1},
            "live_submit": {"exists": True, "size": 1},
            "final_acceptance_gate": {"exists": True, "size": 1},
            "issue_closure": {"exists": True, "size": 1},
        },
        "final_gate_report": {
            "status": "passed",
            "final_delivery_ready": True,
            "failed_checks": [],
            "required_checks": [
                "client_delivery:final_ready",
                "commercial_issue_closure:closed",
                "current_stage_gate:local_ready_or_external_pending",
                "delivery_audit:no_failed_checks",
                "delivery_package:passed",
                "goal_status:passed",
                "operator_pressure:leads_and_actions",
            ],
            "present_required_checks": [
                "client_delivery:final_ready",
                "commercial_issue_closure:closed",
                "current_stage_gate:local_ready_or_external_pending",
                "delivery_audit:no_failed_checks",
                "delivery_package:passed",
                "goal_status:passed",
                "operator_pressure:leads_and_actions",
            ],
            "missing_required_checks": [],
            "failed_required_checks": [],
            "checks_by_name": {
                "current_stage_gate:local_ready_or_external_pending": {"name": "current_stage_gate:local_ready_or_external_pending", "ok": True},
                "goal_status:passed": {"name": "goal_status:passed", "ok": True},
                "client_delivery:final_ready": {"name": "client_delivery:final_ready", "ok": True},
                "delivery_package:passed": {"name": "delivery_package:passed", "ok": True},
                "delivery_audit:no_failed_checks": {"name": "delivery_audit:no_failed_checks", "ok": True},
                "operator_pressure:leads_and_actions": {"name": "operator_pressure:leads_and_actions", "ok": True},
                "commercial_issue_closure:closed": {"name": "commercial_issue_closure:closed", "ok": True},
            },
        },
        "acceptance_verification": {"passed": True, "failures": [], "pending": []},
    }


def final_issue_closure_payload():
    return {
        "schema_version": "reachops.issue_closure_audit.v1",
        "status": "passed",
        "passed": True,
        "github_issues": {
            "range": "#1-#7",
            "expected_open_until_external_acceptance": False,
            "closure_requires_external_validation": False,
        },
        "summary": {
            "issues_total": 7,
            "local_contracts_passed": 7,
            "acceptance_criteria_total": 53,
            "acceptance_criteria_local_passed": 53,
            "acceptance_criteria_external_pending": 0,
            "acceptance_criteria_unclassified": 0,
            "external_pending_count": 0,
            "does_not_claim_all_issues_closed": False,
        },
        "issues": [],
        "external_acceptance_pending": [],
    }


def final_client_delivery_payload(path: str):
    return {
        "status": "passed",
        "readiness": "pass",
        "contract_ok": True,
        "acceptance_ready": True,
        "final_delivery_ready": True,
        "failed_checks": [],
        "delivery_check_path": path,
    }


def write_final_client_delivery_payload(path: Path):
    payload = final_client_delivery_payload(str(path))
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def final_acceptance_gate_payload():
    return {
        "status": "passed",
        "final_delivery_ready": True,
        "failed_checks": [],
        "checks": [
            {"name": "current_stage_gate:local_ready_or_external_pending", "ok": True},
            {"name": "goal_status:passed", "ok": True},
            {"name": "client_delivery:final_ready", "ok": True},
            {"name": "delivery_package:passed", "ok": True},
            {"name": "delivery_audit:no_failed_checks", "ok": True},
            {"name": "operator_pressure:leads_and_actions", "ok": True},
            {"name": "commercial_issue_closure:closed", "ok": True},
        ],
    }


def final_goal_status_payload(status: str = "passed", pending_external_validation: list[str] | None = None):
    pending = pending_external_validation or []
    gate_status = "passed" if status == "passed" and not pending else "ready_for_external_validation"
    return {
        "status": status,
        "pending_external_validation": pending,
        "summary": {"final_pending_external_validation": len(pending), "final_failed": 0},
        "current_stage_gate": {
            "schema_version": "reachops.current_stage_gate.v1",
            "status": gate_status,
            "local_passed": True,
            "local_checks": {
                "delivery_audit_has_no_local_failures": True,
                "client_delivery_reports_real_pilot_boundary": True,
                "client_delivery_does_not_claim_blocked_real_pilot": True,
            },
            "external_validation_pending": pending,
            "does_not_claim_real_pilot_when_blocked": True,
            "real_pilot_evidence": {
                "real_pilot_ready": False if pending else True,
                "status": "external_validation_pending" if pending else "passed",
                "profile_available": 0 if pending else 1,
                "operation_counts": {"candidates": 0 if pending else 1, "actions": 0 if pending else 1, "touched": 0 if pending else 1},
            },
        },
    }


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
            self.assertEqual(manifest["rollback_policy"]["allow_downgrade"], False)
            self.assertEqual(manifest["rollback_policy"]["minimum_version"], "0.0.0")
            self.assertEqual(manifest["evidence"]["schema_version"], "reachops.update_manifest_evidence.v1")
            self.assertTrue(manifest["evidence"]["release_evidence_required"])
            self.assertTrue(manifest["evidence"]["acceptance_summary_required"])
            self.assertTrue(manifest["evidence"]["final_package_check_required"])
            self.assertIn("authorization_handoff", manifest["evidence"]["required_report_files"])
            self.assertIn("client_delivery", manifest["evidence"]["required_report_files"])
            self.assertIn("final_acceptance_gate", manifest["evidence"]["required_report_files"])
            self.assertIn("reachops_delivery_package_check.py --json", "\n".join(manifest["evidence"]["verification_commands"]))

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
            missing_evidence = dict(loaded)
            missing_evidence.pop("evidence", None)
            with self.assertRaisesRegex(ValueError, "manifest evidence contract is required"):
                manager.validate_manifest(missing_evidence)
            incomplete_evidence = json.loads(json.dumps(loaded))
            incomplete_evidence["evidence"]["required_report_files"] = ["final_acceptance_gate"]
            with self.assertRaisesRegex(ValueError, "manifest evidence.required_report_files missing"):
                manager.validate_manifest(incomplete_evidence)
            args = manager.silent_install_args(installer)
            self.assertEqual(args[0], str(installer))
            self.assertIn("/VERYSILENT", args)
            self.assertIn("/SUPPRESSMSGBOXES", args)
            self.assertIn(f'/DIR="{tmp_path / "ReachOps"}"', args)
            self.assertEqual(manager.compare_versions("0.5.0", "0.5.0"), 0)
            self.assertEqual(manager.compare_versions("0.5.1", "0.5.0"), 1)
            self.assertEqual(manager.compare_versions("0.4.9", "0.5.0"), -1)

    def test_reachops_ci_release_baseline_audit_declares_local_and_external_gates(self):
        report = build_reachops_ci_release_baseline_report(run_pip=False)

        self.assertEqual(report["schema_version"], "reachops.ci_release_baseline_audit.v1")
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "passed_with_external_governance_pending")
        self.assertTrue(report["local_checks"]["ci_contract_complete"])
        self.assertTrue(report["local_checks"]["dependency_baseline_passed"])
        self.assertTrue(report["local_checks"]["pip_check_passed"])
        self.assertTrue(report["local_checks"]["release_contract_complete"])
        self.assertTrue(report["release_contract"]["indexes_final_package_report_set"])
        self.assertTrue(report["release_contract"]["rollback_note_exposes_report_recovery_evidence"])
        self.assertEqual(report["supported_platforms"]["python"], "3.11")
        self.assertEqual(report["supported_platforms"]["windows_runner"], "windows-latest")
        self.assertIn("main_branch_protection_requires_pr_review", report["external_governance_pending"])
        self.assertIn("ten_consecutive_ci_runs_without_code_failure", report["external_governance_pending"])
        self.assertTrue(report["does_not_claim_branch_protection"])
        self.assertTrue(report["does_not_claim_ten_green_ci_runs"])
        self.assertFalse(report["github_governance"]["checked"])

    def test_reachops_ci_release_baseline_audit_records_branch_protection_unavailable(self):
        report = build_reachops_ci_release_baseline_report(
            run_pip=False,
            github_governance={
                "branch_protection": {
                    "available": False,
                    "status": "403",
                    "message": "Upgrade to GitHub Pro or make this repository public to enable this feature.",
                },
                "workflow_runs": [
                    {"status": "completed", "conclusion": "success"},
                    {"status": "completed", "conclusion": "success"},
                ],
            },
        )

        self.assertTrue(report["passed"])
        self.assertTrue(report["github_governance"]["checked"])
        self.assertFalse(report["github_governance"]["branch_protection"]["available"])
        self.assertIn("main_branch_protection_requires_pr_review", report["external_governance_pending"])
        self.assertIn("main_branch_protection_requires_successful_checks", report["external_governance_pending"])
        self.assertIn("ten_consecutive_ci_runs_without_code_failure", report["external_governance_pending"])
        self.assertEqual(
            report["external_governance_blockers"][0]["name"],
            "branch_protection_unavailable",
        )
        self.assertTrue(report["does_not_claim_branch_protection"])

    def test_reachops_ci_release_baseline_audit_accepts_verified_github_governance(self):
        report = build_reachops_ci_release_baseline_report(
            run_pip=False,
            github_governance={
                "branch_protection": {
                    "available": True,
                    "payload": {
                        "required_pull_request_reviews": {"required_approving_review_count": 1},
                        "required_status_checks": {
                            "contexts": [
                                "Linux full unit suite (Python 3.11)",
                                "Windows core contracts (Python 3.11)",
                                "Deterministic delivery audits",
                            ]
                        },
                    },
                },
                "workflow_runs": [{"status": "completed", "conclusion": "success"} for _ in range(10)],
            },
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["external_governance_pending"], [])
        self.assertFalse(report["does_not_claim_branch_protection"])
        self.assertFalse(report["does_not_claim_ten_green_ci_runs"])
        self.assertTrue(all(row["status"] == "passed" for row in report["external_governance_gates"]))

    def test_reachops_account_readiness_audit_declares_no_submit_and_external_pilot_boundary(self):
        report = build_reachops_account_readiness_report()

        self.assertEqual(report["schema_version"], "reachops.account_readiness_audit.v1")
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "passed_with_external_account_pilot_pending")
        self.assertTrue(report["local_checks"]["lifecycle_signal_coverage_complete"])
        self.assertTrue(report["local_checks"]["profile_preflight_records_evidence_and_quarantine"])
        self.assertTrue(report["local_checks"]["client_gate_rejects_stale_or_missing_profile_preflight"])
        self.assertTrue(report["local_checks"]["client_delivery_exposes_real_pilot_evidence_boundary"])
        self.assertTrue(report["local_checks"]["live_no_submit_preflight_covers_comment_follow_dm"])
        self.assertTrue(report["local_checks"]["acceptance_summary_verifier_keeps_no_submit_boundary"])
        self.assertTrue(report["no_submit_contract"]["readiness_blocks_do_not_start_browser"])
        self.assertTrue(report["no_submit_contract"]["preflight_actions_do_not_submit"])
        self.assertTrue(report["real_vs_fixture_boundary"]["fixture_data_excluded_by_default"])
        self.assertTrue(report["real_vs_fixture_boundary"]["external_pilot_required"])
        self.assertTrue(report["does_not_claim_certified_30_profiles"])
        self.assertTrue(report["does_not_claim_100_real_no_submit_runs"])
        self.assertIn("certified_30_controlled_profiles", report["external_acceptance_pending"])
        self.assertIn("100_real_no_submit_runs_across_three_industries", report["external_acceptance_pending"])
        self.assertIn("page_state_accuracy_at_least_95_percent", report["external_acceptance_pending"])

    def test_reachops_control_plane_audit_declares_connector_and_cloud_boundary(self):
        report = build_reachops_control_plane_report()

        self.assertEqual(report["schema_version"], "reachops.control_plane_audit.v1")
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "passed_with_external_control_plane_pending")
        self.assertTrue(report["local_checks"]["local_control_surface_is_plan_and_session_bound"])
        self.assertTrue(report["local_checks"]["connector_contract_exists_for_collection_with_evidence"])
        self.assertTrue(report["local_checks"]["action_executor_contract_separates_fixture_from_tiktok"])
        self.assertTrue(report["local_checks"]["packaged_entitlement_enforces_remote_disable"])
        self.assertTrue(report["local_checks"]["support_bundle_policy_is_redacted_by_default"])
        self.assertTrue(report["local_checks"]["current_code_does_not_claim_cloud_control_plane"])
        self.assertTrue(report["connector_boundary"]["non_tiktok_connector_pending"])
        self.assertTrue(report["control_plane_boundary"]["server_side_rbac_pending"])
        self.assertTrue(report["module_boundary"]["monolith_split_pending"])
        self.assertTrue(report["does_not_claim_server_side_rbac"])
        self.assertTrue(report["does_not_claim_non_tiktok_connector_ga"])
        self.assertTrue(report["does_not_claim_web_ui_module_split_complete"])
        self.assertIn("server_side_rbac_enforcement_and_audit", report["external_control_plane_pending"])
        self.assertIn("non_tiktok_connector_contract_implementation", report["external_control_plane_pending"])
        self.assertIn("web_ui_http_api_service_connector_module_split", report["external_control_plane_pending"])

    def test_reachops_issue_closure_audit_maps_issues_to_evidence_and_external_acceptance(self):
        report = build_reachops_issue_closure_report(run_pip=False)

        self.assertEqual(report["schema_version"], "reachops.issue_closure_audit.v1")
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "passed_with_external_acceptance_pending")
        self.assertEqual(report["github_issues"]["range"], "#1-#7")
        self.assertTrue(report["github_issues"]["closure_requires_external_validation"])
        self.assertEqual(report["summary"]["issues_total"], 7)
        self.assertEqual(report["summary"]["local_contracts_passed"], 7)
        self.assertEqual(report["summary"]["acceptance_criteria_total"], 53)
        self.assertEqual(report["summary"]["acceptance_criteria_unclassified"], 0)
        self.assertEqual(report["summary"]["acceptance_criteria_local_passed"], 36)
        self.assertEqual(report["summary"]["acceptance_criteria_external_pending"], 17)
        self.assertGreaterEqual(report["summary"]["external_pending_count"], 1)
        self.assertTrue(report["summary"]["does_not_claim_all_issues_closed"])
        issues = {row["issue_number"]: row for row in report["issues"]}
        self.assertEqual(sorted(issues), [1, 2, 3, 4, 5, 6, 7])
        self.assertTrue(all(row["local_contract_passed"] for row in issues.values()))
        self.assertEqual(sum(row["acceptance_criteria_total"] for row in issues.values()), 53)
        self.assertTrue(all(row["acceptance_criteria_unclassified"] == 0 for row in issues.values()))
        self.assertIn("main_branch_protection_requires_pr_review", issues[1]["external_pending"])
        self.assertIn("certified_30_controlled_profiles", issues[3]["external_pending"])
        self.assertIn("server_side_rbac_enforcement_and_audit", issues[7]["external_pending"])
        external_criteria = {
            criterion["id"]
            for row in issues.values()
            for criterion in row["acceptance_criteria"]
            if criterion["status"] == "external_pending"
        }
        self.assertIn("issue_1_branch_protection_pr_review_checks", external_criteria)
        self.assertIn("issue_3_100_real_no_submit_runs_three_industries", external_criteria)
        self.assertIn("issue_6_three_pilot_customers_attribution_before_ga", external_criteria)
        self.assertIn("issue_7_server_side_roles_permissions_audited", external_criteria)
        self.assertTrue(issues[1]["does_not_claim_issue_closed"])
        self.assertTrue(issues[3]["does_not_claim_issue_closed"])
        self.assertTrue(issues[7]["does_not_claim_issue_closed"])
        issue_2_criteria = {row["id"]: row for row in issues[2]["acceptance_criteria"]}
        self.assertEqual(
            issue_2_criteria["issue_2_unittest_zero_failures_linux_windows"]["evidence_key"],
            "current_review_pr_github_checks_and_local_full_unittest",
        )
        self.assertNotIn("PR #8", json.dumps(report, ensure_ascii=False))

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
        self.assertEqual(checks["产品链接能自动生成获客任务和可执行来源"]["status"], "passed")
        self.assertEqual(checks["产品链接能自动生成获客任务和可执行来源"]["evidence"]["campaign"]["input_type"], "product_url")
        self.assertTrue(checks["产品链接能自动生成获客任务和可执行来源"]["evidence"]["all_sources_executable"])
        self.assertEqual(checks["产品链接能自动生成获客任务和可执行来源"]["evidence"]["direct_product_url_source_count"], 0)
        self.assertEqual(checks["产品链接能自动生成获客任务和可执行来源"]["evidence"]["non_executable_source_types"], [])
        self.assertIn("keyword", checks["产品链接能自动生成获客任务和可执行来源"]["evidence"]["source_types"])
        self.assertIn("hashtag", checks["产品链接能自动生成获客任务和可执行来源"]["evidence"]["source_types"])
        self.assertEqual(checks["达人链接和话题能自动生成获客任务"]["status"], "passed")
        self.assertEqual(checks["达人链接和话题能自动生成获客任务"]["evidence"]["creator"]["campaign"]["input_type"], "creator_url")
        self.assertIn(("creator_url", "https://www.tiktok.com/@beauty_creator"), [tuple(row) for row in checks["达人链接和话题能自动生成获客任务"]["evidence"]["creator"]["source_pairs"]])
        self.assertEqual(checks["达人链接和话题能自动生成获客任务"]["evidence"]["topic"]["campaign"]["input_type"], "hashtag")
        self.assertIn(("hashtag", "skincare"), [tuple(row) for row in checks["达人链接和话题能自动生成获客任务"]["evidence"]["topic"]["source_pairs"]])
        self.assertEqual(checks["账号 readiness 和 no-submit 证据包本地合同可审计"]["status"], "passed")
        self.assertTrue(checks["账号 readiness 和 no-submit 证据包本地合同可审计"]["evidence"]["does_not_claim_certified_30_profiles"])
        self.assertIn("certified_30_controlled_profiles", checks["账号 readiness 和 no-submit 证据包本地合同可审计"]["evidence"]["external_acceptance_pending"])
        self.assertEqual(checks["商业控制面和 connector 解耦边界可审计"]["status"], "passed")
        self.assertTrue(checks["商业控制面和 connector 解耦边界可审计"]["evidence"]["does_not_claim_server_side_rbac"])
        self.assertIn("web_ui_http_api_service_connector_module_split", checks["商业控制面和 connector 解耦边界可审计"]["evidence"]["external_control_plane_pending"])
        self.assertEqual(checks["Issues #1-#7 商业交付闭环证据索引可审计"]["status"], "passed")
        self.assertEqual(checks["Issues #1-#7 商业交付闭环证据索引可审计"]["evidence"]["summary"]["issues_total"], 7)
        self.assertEqual(checks["Issues #1-#7 商业交付闭环证据索引可审计"]["evidence"]["summary"]["local_contracts_passed"], 7)
        self.assertEqual(checks["Issues #1-#7 商业交付闭环证据索引可审计"]["evidence"]["summary"]["acceptance_criteria_total"], 53)
        self.assertEqual(checks["Issues #1-#7 商业交付闭环证据索引可审计"]["evidence"]["summary"]["acceptance_criteria_unclassified"], 0)
        self.assertTrue(checks["Issues #1-#7 商业交付闭环证据索引可审计"]["evidence"]["summary"]["does_not_claim_all_issues_closed"])
        self.assertEqual(checks["升级清单和安装校验机制可用"]["status"], "passed")
        self.assertTrue(checks["升级清单和安装校验机制可用"]["evidence"]["hash_ok"])
        self.assertEqual(checks["客户端交付验收门禁不会把环境阻断当通过"]["status"], "pending_external_validation")
        self.assertTrue(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["contract_ok"])
        self.assertFalse(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["acceptance_ready"])
        self.assertFalse(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["final_delivery_ready"])
        self.assertFalse(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["ok"])
        self.assertEqual(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["status"], "blocked_by_environment")
        self.assertEqual(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["readiness"], "blocked_by_environment")
        self.assertEqual(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["failed_checks"], ["acceptance:ready"])
        self.assertTrue(checks["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["blockers"])
        self.assertEqual(checks["自治客户端核心合同已纳入交付门禁"]["status"], "passed")
        autonomous_core = checks["自治客户端核心合同已纳入交付门禁"]["evidence"]
        self.assertTrue(autonomous_core["ok"])
        self.assertTrue(autonomous_core["checks"]["execution_plan_valid"])
        self.assertTrue(autonomous_core["checks"]["run_session_state_machine"])
        self.assertTrue(autonomous_core["checks"]["page_state_required_classes"])
        self.assertTrue(autonomous_core["checks"]["repair_login_blocks_and_captures"])
        self.assertTrue(autonomous_core["checks"]["risk_gate_blocks_unauthorized_live_submit"])
        self.assertTrue(autonomous_core["checks"]["ai_usage_policy_zero_token"])
        self.assertEqual(checks["网页端通过服务端本地 API 调用指纹浏览器执行获客"]["status"], "passed")
        architecture = checks["网页端通过服务端本地 API 调用指纹浏览器执行获客"]["evidence"]
        self.assertTrue(architecture["passed"])
        self.assertEqual(architecture["operator_entrypoint"], "/api/start")
        self.assertIn("ixBrowser local API", architecture["architecture"])
        self.assertTrue(architecture["checks"]["web_acceptance_persists_client_gate"])
        self.assertTrue(architecture["checks"]["client_entrypoints_default_to_unified_web_console"])
        self.assertTrue(architecture["checks"]["web_api_reports_immediate_headless_exit"])
        self.assertTrue(architecture["checks"]["web_logs_expose_structured_run_result"])
        self.assertTrue(architecture["checks"]["web_api_serializes_concurrent_starts"])
        self.assertTrue(architecture["checks"]["web_api_serializes_start_and_control"])
        self.assertTrue(architecture["checks"]["web_api_product_capability_exposes_top_level_delivery_boundary"])
        self.assertTrue(architecture["checks"]["web_api_passes_live_comment_mode_to_headless"])
        self.assertTrue(architecture["checks"]["web_groups_endpoint_refreshes_profile_registry"])
        self.assertTrue(architecture["checks"]["web_groups_endpoint_has_ixbrowser_timeout"])
        self.assertTrue(architecture["checks"]["web_group_refresh_controls_populate_config_list"])
        self.assertTrue(architecture["checks"]["web_selected_group_drives_start_payload"])
        self.assertTrue(architecture["checks"]["web_start_requires_group_from_ixbrowser_config_list"])
        self.assertTrue(architecture["checks"]["web_ui_disables_start_until_ixbrowser_group_list_ready"])
        self.assertTrue(architecture["checks"]["web_ui_toolbar_and_metrics_are_responsive"])
        self.assertTrue(architecture["checks"]["web_ui_refresh_failures_are_operator_visible"])
        self.assertTrue(architecture["checks"]["web_final_status_uses_operator_default_group"])
        self.assertTrue(architecture["checks"]["web_operator_copy_has_no_test_comment_prompt"])
        self.assertTrue(architecture["checks"]["client_gate_requires_selected_group_profile_list_evidence"])
        self.assertTrue(architecture["checks"]["client_gate_embeds_readonly_ixbrowser_metadata"])
        self.assertTrue(architecture["checks"]["headless_refreshes_profile_groups_before_start"])
        self.assertTrue(architecture["checks"]["headless_live_comment_sets_real_submit_mode"])
        self.assertTrue(architecture["checks"]["headless_collect_mode_does_not_wait_for_action_submit"])
        self.assertTrue(architecture["checks"]["standalone_collect_only_skips_action_processing"])
        self.assertTrue(architecture["checks"]["standalone_live_comment_enables_platform_submit"])
        self.assertTrue(architecture["checks"]["standalone_live_submit_requires_authorization_gate"])
        self.assertTrue(architecture["checks"]["action_router_live_submit_requires_local_evidence_file"])
        self.assertTrue(architecture["checks"]["live_readiness_rejects_fixture_uri_as_real_evidence"])
        self.assertTrue(architecture["checks"]["live_submit_platform_acceptance_requires_local_evidence_details"])
        self.assertTrue(all(architecture["checks"].values()))
        self.assertEqual(checks["最终交付文档合同统一要求客户端门禁、交付包和 final gate"]["status"], "passed")
        final_docs = checks["最终交付文档合同统一要求客户端门禁、交付包和 final gate"]["evidence"]
        self.assertTrue(final_docs["passed"])
        self.assertIn("client gate ready", final_docs["required_contract"])
        self.assertIn("deliverable_index boundary", final_docs["required_contract"])
        self.assertTrue(final_docs["documents"]["pm_delivery_baseline"]["ok"])
        self.assertTrue(all(row["ok"] for row in final_docs["documents"].values()))
        self.assertEqual(checks["项目结构无缓存临时备份冗余文件"]["status"], "passed")
        self.assertTrue(checks["项目结构无缓存临时备份冗余文件"]["evidence"]["passed"])
        self.assertEqual(checks["项目结构无缓存临时备份冗余文件"]["evidence"]["forbidden_count"], 0)
        self.assertEqual(checks["授权门覆盖设备绑定、过期和能力限制"]["status"], "passed")
        self.assertEqual(checks["授权门覆盖设备绑定、过期和能力限制"]["evidence"]["expired"]["error_code"], "LIVE_SUBMIT_LICENSE_EXPIRED")
        self.assertEqual(checks["真实执行成功必须有有效证据"]["status"], "passed")
        self.assertEqual(checks["刷新分组能读取 ixBrowser 配置分组列表"]["status"], "passed")
        self.assertEqual(checks["刷新分组能读取 ixBrowser 配置分组列表"]["evidence"]["counts"]["Canada"], 2)
        self.assertIn(
            {"page": 1, "limit": 100, "group_id": 281726},
            checks["刷新分组能读取 ixBrowser 配置分组列表"]["evidence"]["profile_list_calls"],
        )
        self.assertEqual(checks["选择哪个分组就实际用哪个分组执行"]["status"], "passed")
        self.assertEqual(checks["选择哪个分组就实际用哪个分组执行"]["evidence"]["selected_canada_profile_ids"], ["ca-1", "ca-2"])
        self.assertEqual(checks["能识别并排除异常账号"]["status"], "passed")
        self.assertEqual(checks["能识别并排除异常账号"]["evidence"]["available_profile_ids"], ["10001"])
        self.assertEqual(checks["能识别并排除异常账号"]["evidence"]["errors"]["LOGIN_REQUIRED"], 1)
        self.assertEqual(checks["能识别并排除异常账号"]["evidence"]["errors"]["CAPTCHA_DETECTED"], 1)
        self.assertEqual(checks["能识别并排除异常账号"]["evidence"]["errors"]["PROXY_FAILED"], 1)
        self.assertEqual(checks["客户端按钮和设置接入真实执行链路"]["status"], "passed")
        self.assertTrue(checks["客户端按钮和设置接入真实执行链路"]["evidence"]["settings_consumed_by_execution"])
        self.assertEqual(checks["客户可见设置都有执行证据映射"]["status"], "passed")
        self.assertTrue(checks["客户可见设置都有执行证据映射"]["evidence"]["operator_controls_all_real"])
        self.assertTrue(checks["客户可见设置都有执行证据映射"]["evidence"]["operator_control_evidence"]["账号分组"]["passed"])
        self.assertEqual(checks["客户能看到成功失败换号和错误码"]["status"], "passed")
        result_visibility = checks["客户能看到成功失败换号和错误码"]["evidence"]["operator_result_visibility"]
        self.assertTrue(result_visibility["execution_success"])
        self.assertTrue(result_visibility["failed"])
        self.assertTrue(result_visibility["account_switches"])
        self.assertTrue(result_visibility["error_code"])
        self.assertEqual(checks["开始任务后日志能实时显示执行进度"]["status"], "passed")
        self.assertEqual(checks["异常不弹窗卡死"]["status"], "passed")
        self.assertFalse(any(checks["异常不弹窗卡死"]["evidence"]["popup_hits"].values()))
        self.assertEqual(checks["客户端文案面向运营用户"]["status"], "passed")
        self.assertEqual(checks["客户端文案面向运营用户"]["evidence"]["start_page_technical_hits"], [])
        self.assertEqual(checks["漏斗只显示本轮 Campaign"]["status"], "passed")
        self.assertNotEqual(
            checks["漏斗只显示本轮 Campaign"]["evidence"]["old_funnel"]["campaign_id"],
            checks["漏斗只显示本轮 Campaign"]["evidence"]["new_funnel"]["campaign_id"],
        )
        self.assertEqual(checks["漏斗只显示本轮 Campaign"]["evidence"]["new_execution_success"], 0)
        self.assertEqual(checks["能识别页面打不开和无评论"]["status"], "passed")
        self.assertGreaterEqual(checks["能识别页面打不开和无评论"]["evidence"]["page_open_failed"]["errors"]["CREATOR_PAGE_OPEN_FAILED"], 1)
        self.assertGreaterEqual(checks["能识别页面打不开和无评论"]["evidence"]["empty_comments"]["errors"]["COMMENT_SCAN_EMPTY"], 1)
        self.assertEqual(checks["导出内容包含客户池动作漏斗和错误统计"]["status"], "passed")
        export_evidence = checks["导出内容包含客户池动作漏斗和错误统计"]["evidence"]
        self.assertTrue(export_evidence["has_funnel"])
        self.assertTrue(export_evidence["has_error_counts"])
        self.assertTrue(export_evidence["outreach_executions_present"])
        self.assertTrue(export_evidence["execution_summary_present"])
        self.assertTrue(export_evidence["execution_summary_total_matches"])
        self.assertTrue(export_evidence["execution_summary_has_switches"])
        self.assertTrue(export_evidence["execution_columns_ok"])
        self.assertGreater(export_evidence["customer_csv_rows"], 0)
        self.assertGreater(export_evidence["action_csv_rows"], 0)
        self.assertGreaterEqual(
            checks["真实执行成功必须有有效证据"]["evidence"]["result"]["errors"]["LIVE_SUBMIT_EVIDENCE_MISSING"],
            1,
        )

    def test_reachops_goal_status_resolves_client_delivery_gate_independently(self):
        class Args:
            target = "anti aging serum"
            base_dir = ""

        audit_result = run_reachops_delivery_audit(Args())
        report = build_goal_status_report(
            audit_result,
            client_delivery=final_client_delivery_payload("reports/acceptance_remediation/latest_delivery_check.json"),
        )

        self.assertEqual(report["status"], "ready_for_external_validation")
        self.assertNotIn("客户端交付验收门禁不会把环境阻断当通过", report["pending_external_validation"])
        self.assertIn("授权允许时能真实执行", report["pending_external_validation"])
        self.assertIn("真实 TikTok 平台提交", report["pending_external_validation"])
        rows = {row["name"]: row for row in report["final_acceptance"]}
        self.assertEqual(rows["客户端交付验收门禁不会把环境阻断当通过"]["status"], "passed")
        self.assertTrue(
            rows["客户端交付验收门禁不会把环境阻断当通过"]["evidence"]["client_delivery_gate"][
                "final_delivery_ready"
            ]
        )

    def test_reachops_goal_status_exposes_current_stage_external_gate(self):
        class Args:
            target = "anti aging serum"
            base_dir = ""

        audit_result = run_reachops_delivery_audit(Args())
        client_delivery = {
            "status": "blocked_by_accounts",
            "readiness": "blocked_by_accounts",
            "acceptance_ready": False,
            "final_delivery_ready": False,
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "real_pilot_evidence": {
                "schema_version": "reachops.real_pilot_evidence_boundary.v1",
                "real_pilot_ready": False,
                "status": "external_validation_pending",
                "fixture_or_dry_run_claimed": False,
                "no_submit_preserved": True,
                "profile_available": 0,
                "operation_counts": {"candidates": 0, "actions": 0, "touched": 0},
                "external_acceptance_pending": ["profile_available_zero", "candidate_count_zero"],
            },
        }

        report = build_goal_status_report(audit_result, client_delivery=client_delivery)

        gate = report["current_stage_gate"]
        self.assertEqual(gate["schema_version"], "reachops.current_stage_gate.v1")
        self.assertEqual(gate["status"], "ready_for_external_validation")
        self.assertTrue(gate["local_passed"])
        self.assertTrue(gate["local_checks"]["delivery_audit_has_no_local_failures"])
        self.assertTrue(gate["local_checks"]["client_delivery_reports_real_pilot_boundary"])
        self.assertTrue(gate["does_not_claim_real_pilot_when_blocked"])
        self.assertIn("profile_available_zero", gate["external_validation_pending"])
        self.assertFalse(gate["real_pilot_evidence"]["real_pilot_ready"])

    def test_reachops_goal_status_cli_uses_current_client_delivery_gate(self):
        class Args:
            target = "anti aging serum"
            base_dir = ""

        audit_result = run_reachops_delivery_audit(Args())
        client_payload = final_client_delivery_payload("reports/acceptance_remediation/latest_delivery_check.json")
        out = io.StringIO()

        with patch("tools.reachops_goal_status_report.run_default_audit", return_value=audit_result), patch(
            "tools.reachops_goal_status_report.current_client_delivery",
            return_value=client_payload,
        ), redirect_stdout(out):
            rc = reachops_goal_status_main(["--json"])

        self.assertEqual(rc, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["status"], "ready_for_external_validation")
        self.assertNotIn("客户端交付验收门禁不会把环境阻断当通过", report["pending_external_validation"])
        rows = {row["name"]: row for row in report["final_acceptance"]}
        self.assertEqual(rows["客户端交付验收门禁不会把环境阻断当通过"]["status"], "passed")

    def test_reachops_repository_cleanliness_check_finds_redundant_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ReachOps").mkdir()
            (root / "ReachOps" / "valid.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "ReachOps" / "__pycache__").mkdir()
            (root / "ReachOps" / "leftover.pyc").write_bytes(b"bytecode")
            (root / "notes.bak").write_text("old", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv" / "__pycache__").mkdir()

            failed = scan_repository_cleanliness(root)
            self.assertEqual(failed["status"], "failed")
            paths = {row["path"] for row in failed["forbidden_items"]}
            self.assertIn("ReachOps/__pycache__", paths)
            self.assertIn("ReachOps/leftover.pyc", paths)
            self.assertIn("notes.bak", paths)
            self.assertNotIn(".venv/__pycache__", paths)

            for item in [root / "ReachOps" / "__pycache__", root / "ReachOps" / "leftover.pyc", root / "notes.bak"]:
                if item.is_dir():
                    item.rmdir()
                else:
                    item.unlink()
            passed = scan_repository_cleanliness(root)
            self.assertEqual(passed["status"], "passed")
            self.assertEqual(passed["forbidden_count"], 0)
            self.assertEqual(passed["git_worktree"]["status"], "not_git_repository")

    def test_reachops_repository_cleanliness_check_requires_clean_git_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / "ReachOps").mkdir()
            (root / "ReachOps" / "valid.py").write_text("print('ok')\n", encoding="utf-8")
            clean = scan_repository_cleanliness(root)
            self.assertEqual(clean["status"], "failed")
            self.assertEqual(clean["git_worktree"]["status"], "dirty")
            self.assertEqual(clean["git_worktree"]["dirty_items"][0]["path"], "ReachOps/valid.py")

            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=ReachOps Test",
                    "-c",
                    "user.email=reachops-test@example.test",
                    "commit",
                    "-m",
                    "baseline",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            clean = scan_repository_cleanliness(root)
            self.assertEqual(clean["status"], "passed")
            self.assertEqual(clean["git_worktree"]["status"], "clean")

            (root / "scratch.txt").write_text("local scratch\n", encoding="utf-8")
            dirty = scan_repository_cleanliness(root)
            self.assertEqual(dirty["status"], "failed")
            self.assertEqual(dirty["git_worktree"]["dirty_count"], 1)
            self.assertEqual(dirty["git_worktree"]["dirty_items"][0]["path"], "scratch.txt")

    def test_reachops_repository_cleanliness_ignores_gitignored_runtime_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
            (root / "ReachOps").mkdir()
            (root / "ReachOps" / "valid.py").write_text("print('ok')\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore", "ReachOps/valid.py"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=ReachOps Test",
                    "-c",
                    "user.email=reachops-test@example.test",
                    "commit",
                    "-m",
                    "baseline",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )

            (root / "ReachOps" / "__pycache__").mkdir()
            (root / "ReachOps" / "__pycache__" / "valid.cpython-311.pyc").write_bytes(b"bytecode")
            clean = scan_repository_cleanliness(root)

            self.assertEqual(clean["status"], "passed")
            self.assertEqual(clean["forbidden_count"], 0)
            self.assertGreaterEqual(clean["ignored_generated_count"], 1)
            ignored_paths = {row["path"] for row in clean["ignored_generated_items"]}
            self.assertIn("ReachOps/__pycache__", ignored_paths)

    def test_reachops_repository_cleanliness_blocks_tracked_generated_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
            (root / "ReachOps" / "__pycache__").mkdir(parents=True)
            (root / "ReachOps" / "__pycache__" / "valid.cpython-311.pyc").write_bytes(b"bytecode")
            subprocess.run(
                ["git", "add", ".gitignore", "-f", "ReachOps/__pycache__/valid.cpython-311.pyc"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=ReachOps Test",
                    "-c",
                    "user.email=reachops-test@example.test",
                    "commit",
                    "-m",
                    "tracked cache",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )

            failed = scan_repository_cleanliness(root)

            self.assertEqual(failed["status"], "failed")
            paths = {row["path"] for row in failed["forbidden_items"]}
            self.assertIn("ReachOps/__pycache__/valid.cpython-311.pyc", paths)
            self.assertTrue(any(row.get("detail") == "forbidden_generated_artifact_tracked_by_git" for row in failed["forbidden_items"]))

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
                "summary": {"stages_passed": 3, "stages_pending_external_validation": 2, "stages_failed": 0},
                "pending_external_validation": ["授权允许时能真实执行", "真实 TikTok 平台提交", "客户端交付验收门禁不会把环境阻断当通过"],
            },
        }

        pending = verify_reachops_acceptance_summary(base_summary)
        self.assertFalse(pending["passed"])
        self.assertIn("external_platform_validation", pending["pending"])
        self.assertIn("live_authorization_execution_validation", pending["pending"])
        self.assertIn("real_tiktok_platform_submit", pending["pending"])
        self.assertIn("client_delivery_acceptance_gate", pending["pending"])

        allowed = verify_reachops_acceptance_summary(base_summary, allow_external_pending=True)
        self.assertTrue(allowed["passed"])
        self.assertIn("client_delivery_acceptance_gate", allowed["pending"])
        self.assertEqual(allowed["live_readiness"]["status"], "skipped")
        self.assertEqual(allowed["live_validation"]["status"], "blocked")
        self.assertTrue(allowed["live_validation"]["no_browser_started"])
        self.assertTrue(allowed["live_validation"]["no_submit"])
        self.assertTrue(allowed["live_readiness"]["no_browser_started"])
        self.assertEqual(allowed["goal_status"]["status"], "ready_for_external_validation")
        self.assertIn("授权允许时能真实执行", allowed["goal_status"]["pending_external_validation"])
        self.assertIn("真实 TikTok 平台提交", allowed["goal_status"]["pending_external_validation"])
        self.assertIn("客户端交付验收门禁不会把环境阻断当通过", allowed["goal_status"]["pending_external_validation"])
        self.assertEqual(allowed["operator_pressure"]["campaign_count"], 3)
        self.assertEqual(allowed["final_acceptance_gate"]["status"], "")

        missing_client_gate_summary = json.loads(json.dumps(base_summary))
        missing_client_gate_summary["delivery_audit"]["pending_external_validation"] = 3
        missing_client_gate_summary["delivery_audit"]["effective_pending_external_validation"] = 3
        missing_client_gate_summary["goal_status"]["pending_external_validation"] = ["授权允许时能真实执行", "真实 TikTok 平台提交"]
        missing_client_gate = verify_reachops_acceptance_summary(missing_client_gate_summary, allow_external_pending=True)
        self.assertFalse(missing_client_gate["passed"])
        self.assertIn("goal_status_missing_current_pending", missing_client_gate["failures"])

        string_missing_input_summary = json.loads(json.dumps(base_summary))
        string_missing_input_summary["live_validation"]["missing_inputs"] = "有效激活状态文件"
        string_missing_input = verify_reachops_acceptance_summary(string_missing_input_summary, allow_external_pending=True)
        self.assertEqual(string_missing_input["live_validation"]["missing_inputs"], ["有效激活状态文件"])

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
        passed_summary["repository_cleanliness"] = {
            "status": "passed",
            "passed": True,
            "forbidden_count": 0,
            "json_path": "reports/reachops_acceptance/current/repository_cleanliness_payload.json",
        }
        passed_summary["windows_package_preflight"] = {
            "status": "ready_for_windows_build",
            "ready_for_windows_build": True,
            "final_delivery_ready": False,
            "build_contract": {
                "default_build_requires_installer": True,
                "skip_installer_is_non_final": True,
            },
            "json_path": "reports/reachops_acceptance/current/windows_package_preflight.json",
        }
        passed_summary["client_delivery"] = {
            "status": "passed",
            "readiness": "pass",
            "contract_ok": True,
            "acceptance_ready": True,
            "final_delivery_ready": True,
            "failed_checks": [],
            "json_path": "reports/reachops_acceptance/current/client_delivery.json",
        }
        passed_summary["final_acceptance_gate"] = {
            "status": "passed",
            "final_delivery_ready": True,
            "failed_checks": [],
            "json_path": "reports/reachops_acceptance/current/final_acceptance_gate.json",
        }
        passed_summary["issue_closure"] = {
            "schema_version": "reachops.issue_closure_audit.v1",
            "status": "passed",
            "passed": True,
            "github_issues": {"closure_requires_external_validation": False},
            "summary": {
                "issues_total": 7,
                "acceptance_criteria_total": 53,
                "acceptance_criteria_external_pending": 0,
                "acceptance_criteria_unclassified": 0,
                "external_pending_count": 0,
            },
            "external_acceptance_pending": [],
            "json_path": "reports/reachops_acceptance/current/issue_closure_payload.json",
        }
        passed_summary["live_readiness"] = {
            "status": "ready",
            "ready": True,
            "no_browser_started": False,
            "no_submit": True,
        }
        passed_summary["live_acceptance_status"] = {
            "status": "passed",
            "final_delivery_ready": True,
            "ready_for_live_submit": True,
            "failed_checks": [],
            "local_inputs": {"usable": True},
            "activation": {"ready": True},
            "live_validation": {
                "missing_inputs": [],
                "selected_profile_ids": ["profile-a"],
            },
        }
        passed_summary["authorization_handoff"] = {
            "status": "created",
            "exists": True,
            "final_delivery_ready": False,
            "no_browser_started": True,
            "no_submit": True,
            "bundle_path": "reports/reachops_acceptance/current/latest_reachops_authorization_handoff.zip",
            "readiness_status": "passed",
            "readiness_report_path": "reports/reachops_acceptance/current/latest_live_acceptance_readiness.md",
            "readiness_json_path": "reports/reachops_acceptance/current/latest_live_acceptance_readiness.json",
            "json_path": "reports/reachops_acceptance/current/authorization_handoff_payload.json",
        }
        passed_summary["live_preflight"] = {
            "status": "completed",
            "preflight_action_statuses": {
                "comment_reply": [{"status": "success"}],
                "follow_review": [{"status": "success"}],
                "dm_review": [{"status": "success"}],
            },
            "missing_preflight_action_types": [],
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
            "passed": True,
            "live_submit": True,
            "activation_status_loaded": True,
            "activation_status_source": "C:/Users/aofa/AppData/Local/ReachOps/config/reachops_activation_status.json",
            "activation_status_path": "reports/reachops_acceptance/live_submit/config/reachops_activation_status.json",
            "summary": {
                "selected_actions": 3,
                "success": 3,
                "failed": 0,
                "skipped": 0,
                "results": [
                    {"action_type": "comment_reply", "status": "success", "action_id": "comment_reply-1", "profile_id": "profile-a"},
                    {"action_type": "follow_review", "status": "success", "action_id": "follow_review-1", "profile_id": "profile-a"},
                    {"action_type": "dm_review", "status": "success", "action_id": "dm_review-1", "profile_id": "profile-a"},
                ],
            },
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
        self.assertEqual(passed["repository_cleanliness"]["status"], "passed")
        self.assertEqual(passed["repository_cleanliness"]["forbidden_count"], 0)
        self.assertTrue(passed["repository_cleanliness"]["json_path"].endswith("repository_cleanliness_payload.json"))
        self.assertEqual(passed["windows_package_preflight"]["status"], "ready_for_windows_build")
        self.assertTrue(passed["windows_package_preflight"]["ready_for_windows_build"])
        self.assertTrue(passed["windows_package_preflight"]["default_build_requires_installer"])
        self.assertTrue(passed["windows_package_preflight"]["skip_installer_is_non_final"])
        self.assertTrue(passed["windows_package_preflight"]["json_path"].endswith("windows_package_preflight.json"))
        self.assertEqual(passed["client_delivery"]["status"], "passed")
        self.assertEqual(passed["client_delivery"]["readiness"], "pass")
        self.assertTrue(passed["client_delivery"]["final_delivery_ready"])
        self.assertTrue(passed["client_delivery"]["json_path"].endswith("client_delivery.json"))
        self.assertEqual(passed["final_acceptance_gate"]["status"], "passed")
        self.assertTrue(passed["final_acceptance_gate"]["final_delivery_ready"])
        self.assertTrue(passed["final_acceptance_gate"]["json_path"].endswith("final_acceptance_gate.json"))
        self.assertEqual(passed["issue_closure"]["status"], "passed")
        self.assertTrue(passed["issue_closure"]["passed"])
        self.assertEqual(passed["issue_closure"]["issues_total"], 7)
        self.assertEqual(passed["issue_closure"]["acceptance_criteria_total"], 53)
        self.assertEqual(passed["issue_closure"]["acceptance_criteria_external_pending"], 0)
        self.assertEqual(passed["issue_closure"]["external_pending_count"], 0)
        self.assertIs(passed["issue_closure"]["closure_requires_external_validation"], False)
        self.assertTrue(passed["issue_closure"]["json_path"].endswith("issue_closure_payload.json"))
        self.assertEqual(passed["live_acceptance_status"]["status"], "passed")
        self.assertTrue(passed["live_acceptance_status"]["final_delivery_ready"])
        self.assertTrue(passed["live_acceptance_status"]["ready_for_live_submit"])
        self.assertTrue(passed["live_acceptance_status"]["local_inputs_usable"])
        self.assertTrue(passed["live_acceptance_status"]["activation_ready"])
        self.assertEqual(passed["live_acceptance_status"]["selected_profile_ids"], ["profile-a"])
        self.assertEqual(passed["authorization_handoff"]["status"], "created")
        self.assertTrue(passed["authorization_handoff"]["exists"])
        self.assertTrue(passed["authorization_handoff"]["no_browser_started"])
        self.assertTrue(passed["authorization_handoff"]["no_submit"])
        self.assertTrue(passed["authorization_handoff"]["json_path"].endswith("authorization_handoff_payload.json"))
        self.assertTrue(passed["authorization_handoff"]["readiness_report_path"].endswith("latest_live_acceptance_readiness.md"))
        self.assertTrue(passed["authorization_handoff"]["readiness_json_path"].endswith("latest_live_acceptance_readiness.json"))

        missing_authorization_handoff_summary = json.loads(json.dumps(passed_summary))
        missing_authorization_handoff_summary.pop("authorization_handoff")
        missing_authorization_handoff = verify_reachops_acceptance_summary(missing_authorization_handoff_summary)
        self.assertFalse(missing_authorization_handoff["passed"])
        self.assertIn("authorization_handoff_missing", missing_authorization_handoff["failures"])

        unsafe_authorization_handoff_summary = json.loads(json.dumps(passed_summary))
        unsafe_authorization_handoff_summary["authorization_handoff"] = {
            "status": "failed",
            "exists": False,
            "no_browser_started": False,
            "no_submit": False,
            "bundle_path": "",
            "readiness_report_path": "",
            "readiness_json_path": "",
            "json_path": "",
        }
        unsafe_authorization_handoff = verify_reachops_acceptance_summary(unsafe_authorization_handoff_summary)
        self.assertFalse(unsafe_authorization_handoff["passed"])
        self.assertIn("authorization_handoff_not_created", unsafe_authorization_handoff["failures"])
        self.assertIn("authorization_handoff_bundle_missing", unsafe_authorization_handoff["failures"])
        self.assertIn("authorization_handoff_opened_browser", unsafe_authorization_handoff["failures"])
        self.assertIn("authorization_handoff_submitted_action", unsafe_authorization_handoff["failures"])
        self.assertIn("authorization_handoff_bundle_path_missing", unsafe_authorization_handoff["failures"])
        self.assertIn("authorization_handoff_json_path_missing", unsafe_authorization_handoff["failures"])
        self.assertIn("authorization_handoff_readiness_report_path_missing", unsafe_authorization_handoff["failures"])
        self.assertIn("authorization_handoff_readiness_json_path_missing", unsafe_authorization_handoff["failures"])

        missing_live_acceptance_status_summary = json.loads(json.dumps(passed_summary))
        missing_live_acceptance_status_summary.pop("live_acceptance_status")
        missing_live_acceptance_status = verify_reachops_acceptance_summary(missing_live_acceptance_status_summary)
        self.assertFalse(missing_live_acceptance_status["passed"])
        self.assertIn("live_acceptance_status_missing", missing_live_acceptance_status["failures"])

        blocked_live_acceptance_summary = json.loads(json.dumps(passed_summary))
        blocked_live_acceptance_summary["live_acceptance_status"] = {
            "status": "blocked",
            "final_delivery_ready": False,
            "ready_for_live_submit": False,
            "failed_checks": ["local_inputs:usable", "activation:ready"],
            "local_inputs": {"usable": False},
            "activation": {"ready": False},
            "live_validation": {
                "missing_inputs": ["ixBrowser 数字 Profile ID", "有效激活状态文件"],
                "selected_profile_ids": [],
            },
        }
        blocked_live_acceptance = verify_reachops_acceptance_summary(blocked_live_acceptance_summary)
        self.assertFalse(blocked_live_acceptance["passed"])
        self.assertIn("live_acceptance_status_not_passed", blocked_live_acceptance["failures"])
        self.assertIn("live_acceptance_status_not_ready_for_live_submit", blocked_live_acceptance["failures"])
        self.assertIn("live_acceptance_status_local_inputs_unusable", blocked_live_acceptance["failures"])
        self.assertIn("live_acceptance_status_activation_not_ready", blocked_live_acceptance["failures"])
        self.assertIn("live_acceptance_status_profile_ids_missing", blocked_live_acceptance["failures"])
        self.assertIn("live_acceptance_status_missing_inputs", blocked_live_acceptance["failures"])
        self.assertIn("live_acceptance_status_failed_checks", blocked_live_acceptance["failures"])

        missing_cleanliness_summary = json.loads(json.dumps(passed_summary))
        missing_cleanliness_summary.pop("repository_cleanliness")
        missing_cleanliness = verify_reachops_acceptance_summary(missing_cleanliness_summary)
        self.assertFalse(missing_cleanliness["passed"])
        self.assertIn("repository_cleanliness_missing", missing_cleanliness["failures"])

        dirty_cleanliness_summary = json.loads(json.dumps(passed_summary))
        dirty_cleanliness_summary["repository_cleanliness"] = {
            "status": "failed",
            "passed": False,
            "forbidden_count": 1,
        }
        dirty_cleanliness = verify_reachops_acceptance_summary(dirty_cleanliness_summary)
        self.assertFalse(dirty_cleanliness["passed"])
        self.assertIn("repository_cleanliness_not_passed", dirty_cleanliness["failures"])
        self.assertIn("repository_cleanliness_failed", dirty_cleanliness["failures"])
        self.assertIn("repository_cleanliness_forbidden_items", dirty_cleanliness["failures"])

        missing_cleanliness_path_summary = json.loads(json.dumps(passed_summary))
        missing_cleanliness_path_summary["repository_cleanliness"].pop("json_path")
        missing_cleanliness_path = verify_reachops_acceptance_summary(missing_cleanliness_path_summary)
        self.assertFalse(missing_cleanliness_path["passed"])
        self.assertIn("repository_cleanliness_json_path_missing", missing_cleanliness_path["failures"])

        missing_windows_preflight_summary = json.loads(json.dumps(passed_summary))
        missing_windows_preflight_summary.pop("windows_package_preflight")
        missing_windows_preflight = verify_reachops_acceptance_summary(missing_windows_preflight_summary)
        self.assertFalse(missing_windows_preflight["passed"])
        self.assertIn("windows_package_preflight_missing", missing_windows_preflight["failures"])

        bad_windows_preflight_summary = json.loads(json.dumps(passed_summary))
        bad_windows_preflight_summary["windows_package_preflight"] = {
            "status": "failed",
            "ready_for_windows_build": False,
            "build_contract": {},
        }
        bad_windows_preflight = verify_reachops_acceptance_summary(bad_windows_preflight_summary)
        self.assertFalse(bad_windows_preflight["passed"])
        self.assertIn("windows_package_preflight_not_ready", bad_windows_preflight["failures"])
        self.assertIn("windows_package_preflight_failed", bad_windows_preflight["failures"])
        self.assertIn("windows_package_preflight_installer_contract_missing", bad_windows_preflight["failures"])
        self.assertIn("windows_package_preflight_skip_installer_contract_missing", bad_windows_preflight["failures"])

        missing_windows_preflight_path_summary = json.loads(json.dumps(passed_summary))
        missing_windows_preflight_path_summary["windows_package_preflight"].pop("json_path")
        missing_windows_preflight_path = verify_reachops_acceptance_summary(missing_windows_preflight_path_summary)
        self.assertFalse(missing_windows_preflight_path["passed"])
        self.assertIn("windows_package_preflight_json_path_missing", missing_windows_preflight_path["failures"])

        missing_client_delivery_summary = json.loads(json.dumps(passed_summary))
        missing_client_delivery_summary.pop("client_delivery")
        missing_client_delivery = verify_reachops_acceptance_summary(missing_client_delivery_summary)
        self.assertFalse(missing_client_delivery["passed"])
        self.assertIn("client_delivery_missing", missing_client_delivery["failures"])

        bad_client_delivery_summary = json.loads(json.dumps(passed_summary))
        bad_client_delivery_summary["client_delivery"]["final_delivery_ready"] = False
        bad_client_delivery_summary["client_delivery"]["failed_checks"] = ["ixbrowser:selected_group_count_consistent"]
        bad_client_delivery = verify_reachops_acceptance_summary(bad_client_delivery_summary)
        self.assertFalse(bad_client_delivery["passed"])
        self.assertIn("client_delivery_final_not_ready", bad_client_delivery["failures"])
        self.assertIn("client_delivery_failed_checks", bad_client_delivery["failures"])

        missing_final_gate_summary = json.loads(json.dumps(passed_summary))
        missing_final_gate_summary.pop("final_acceptance_gate")
        missing_final_gate = verify_reachops_acceptance_summary(missing_final_gate_summary)
        self.assertFalse(missing_final_gate["passed"])
        self.assertIn("final_acceptance_gate_missing", missing_final_gate["failures"])

        bad_final_gate_summary = json.loads(json.dumps(passed_summary))
        bad_final_gate_summary["final_acceptance_gate"] = {
            "status": "not_ready",
            "final_delivery_ready": False,
            "failed_checks": ["delivery_package:passed"],
        }
        bad_final_gate = verify_reachops_acceptance_summary(bad_final_gate_summary)
        self.assertFalse(bad_final_gate["passed"])
        self.assertIn("final_acceptance_gate_not_passed", bad_final_gate["failures"])
        self.assertIn("final_acceptance_gate_not_ready", bad_final_gate["failures"])
        self.assertIn("final_acceptance_gate_failed_checks", bad_final_gate["failures"])

        missing_final_gate_path_summary = json.loads(json.dumps(passed_summary))
        missing_final_gate_path_summary["final_acceptance_gate"].pop("json_path")
        missing_final_gate_path = verify_reachops_acceptance_summary(missing_final_gate_path_summary)
        self.assertFalse(missing_final_gate_path["passed"])
        self.assertIn("final_acceptance_gate_json_path_missing", missing_final_gate_path["failures"])

        missing_issue_closure_summary = json.loads(json.dumps(passed_summary))
        missing_issue_closure_summary.pop("issue_closure")
        missing_issue_closure = verify_reachops_acceptance_summary(missing_issue_closure_summary)
        self.assertFalse(missing_issue_closure["passed"])
        self.assertIn("issue_closure_missing", missing_issue_closure["failures"])

        pending_issue_closure_summary = json.loads(json.dumps(passed_summary))
        pending_issue_closure_summary["issue_closure"]["summary"]["acceptance_criteria_external_pending"] = 1
        pending_issue_closure_summary["issue_closure"]["summary"]["external_pending_count"] = 2
        pending_issue_closure_summary["issue_closure"]["github_issues"]["closure_requires_external_validation"] = True
        pending_issue_closure_summary["issue_closure"]["external_acceptance_pending"] = ["issue_3_100_real_no_submit_runs_three_industries"]
        pending_issue_closure = verify_reachops_acceptance_summary(pending_issue_closure_summary)
        self.assertFalse(pending_issue_closure["passed"])
        self.assertIn("issue_closure_external_pending", pending_issue_closure["failures"])
        self.assertIn("issue_closure_external_pending_items", pending_issue_closure["failures"])
        self.assertIn("issue_closure_external_acceptance_pending", pending_issue_closure["failures"])
        self.assertIn("issue_closure_requires_external_validation", pending_issue_closure["failures"])

        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "acceptance"
            report_dir.mkdir()
            summary_path = report_dir / "acceptance_summary.json"
            (report_dir / "repository_cleanliness_payload.json").write_text("{}", encoding="utf-8")
            (report_dir / "windows_package_preflight.json").write_text("{}", encoding="utf-8")
            (report_dir / "client_delivery.json").write_text("{}", encoding="utf-8")
            (report_dir / "final_acceptance_gate.json").write_text("{}", encoding="utf-8")
            (report_dir / "issue_closure_payload.json").write_text("{}", encoding="utf-8")
            (report_dir / "authorization_handoff_payload.json").write_text("{}", encoding="utf-8")
            (report_dir / "latest_live_acceptance_readiness.md").write_text("# ready", encoding="utf-8")
            (report_dir / "latest_live_acceptance_readiness.json").write_text("{}", encoding="utf-8")
            path_checked_summary = json.loads(json.dumps(passed_summary))
            path_checked_summary["repository_cleanliness"]["json_path"] = "repository_cleanliness_payload.json"
            path_checked_summary["windows_package_preflight"]["json_path"] = "windows_package_preflight.json"
            path_checked_summary["client_delivery"]["json_path"] = "client_delivery.json"
            path_checked_summary["final_acceptance_gate"]["json_path"] = "final_acceptance_gate.json"
            path_checked_summary["issue_closure"]["json_path"] = "issue_closure_payload.json"
            path_checked_summary["authorization_handoff"]["json_path"] = "authorization_handoff_payload.json"
            path_checked_summary["authorization_handoff"]["readiness_report_path"] = "latest_live_acceptance_readiness.md"
            path_checked_summary["authorization_handoff"]["readiness_json_path"] = "latest_live_acceptance_readiness.json"
            path_checked = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertTrue(path_checked["passed"])
            self.assertTrue(path_checked["repository_cleanliness"]["json_exists"])
            self.assertTrue(path_checked["windows_package_preflight"]["json_exists"])
            self.assertTrue(path_checked["client_delivery"]["json_exists"])
            self.assertTrue(path_checked["final_acceptance_gate"]["json_exists"])
            self.assertTrue(path_checked["issue_closure"]["json_exists"])
            self.assertTrue(path_checked["authorization_handoff"]["json_exists"])
            self.assertTrue(path_checked["authorization_handoff"]["readiness_report_exists"])
            self.assertTrue(path_checked["authorization_handoff"]["readiness_json_exists"])
            self.assertTrue(path_checked["repository_cleanliness"]["json_inside_summary_dir"])
            self.assertTrue(path_checked["windows_package_preflight"]["json_inside_summary_dir"])
            self.assertTrue(path_checked["client_delivery"]["json_inside_summary_dir"])
            self.assertTrue(path_checked["final_acceptance_gate"]["json_inside_summary_dir"])
            self.assertTrue(path_checked["issue_closure"]["json_inside_summary_dir"])
            self.assertTrue(path_checked["authorization_handoff"]["json_inside_summary_dir"])
            self.assertTrue(path_checked["authorization_handoff"]["readiness_report_inside_summary_dir"])
            self.assertTrue(path_checked["authorization_handoff"]["readiness_json_inside_summary_dir"])

            (report_dir / "repository_cleanliness_payload.json").unlink()
            missing_report_file = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(missing_report_file["passed"])
            self.assertIn("repository_cleanliness_json_missing", missing_report_file["failures"])

            (report_dir / "repository_cleanliness_payload.json").write_text("{}", encoding="utf-8")
            (report_dir / "windows_package_preflight.json").unlink()
            missing_preflight_report_file = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(missing_preflight_report_file["passed"])
            self.assertIn("windows_package_preflight_json_missing", missing_preflight_report_file["failures"])

            (report_dir / "windows_package_preflight.json").write_text("{}", encoding="utf-8")
            (report_dir / "client_delivery.json").unlink()
            missing_client_delivery_report_file = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(missing_client_delivery_report_file["passed"])
            self.assertIn("client_delivery_json_missing", missing_client_delivery_report_file["failures"])

            (report_dir / "client_delivery.json").write_text("{}", encoding="utf-8")
            (report_dir / "final_acceptance_gate.json").write_text("", encoding="utf-8")
            empty_final_gate_file = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(empty_final_gate_file["passed"])
            self.assertIn("final_acceptance_gate_json_empty", empty_final_gate_file["failures"])

            (report_dir / "final_acceptance_gate.json").write_text("{}", encoding="utf-8")
            (report_dir / "issue_closure_payload.json").unlink()
            missing_issue_file = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(missing_issue_file["passed"])
            self.assertIn("issue_closure_json_missing", missing_issue_file["failures"])

            (report_dir / "issue_closure_payload.json").write_text("{}", encoding="utf-8")
            (report_dir / "authorization_handoff_payload.json").unlink()
            missing_handoff_file = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(missing_handoff_file["passed"])
            self.assertIn("authorization_handoff_json_missing", missing_handoff_file["failures"])

            (report_dir / "authorization_handoff_payload.json").write_text("{}", encoding="utf-8")
            (report_dir / "latest_live_acceptance_readiness.md").write_text("", encoding="utf-8")
            empty_handoff_readiness_report = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(empty_handoff_readiness_report["passed"])
            self.assertIn("authorization_handoff_readiness_report_empty", empty_handoff_readiness_report["failures"])

            (report_dir / "latest_live_acceptance_readiness.md").write_text("# ready", encoding="utf-8")
            (report_dir / "latest_live_acceptance_readiness.json").unlink()
            missing_handoff_readiness_json = verify_reachops_acceptance_summary(path_checked_summary, summary_path=summary_path)
            self.assertFalse(missing_handoff_readiness_json["passed"])
            self.assertIn("authorization_handoff_readiness_json_missing", missing_handoff_readiness_json["failures"])

            (report_dir / "latest_live_acceptance_readiness.json").write_text("{}", encoding="utf-8")
            outside_dir = Path(tmp) / "outside"
            outside_dir.mkdir()
            (outside_dir / "repository_cleanliness_payload.json").write_text("{}", encoding="utf-8")
            (outside_dir / "windows_package_preflight.json").write_text("{}", encoding="utf-8")
            (outside_dir / "client_delivery.json").write_text("{}", encoding="utf-8")
            (outside_dir / "final_acceptance_gate.json").write_text("{}", encoding="utf-8")
            (outside_dir / "issue_closure_payload.json").write_text("{}", encoding="utf-8")
            (outside_dir / "authorization_handoff_payload.json").write_text("{}", encoding="utf-8")
            (outside_dir / "latest_live_acceptance_readiness.md").write_text("# ready", encoding="utf-8")
            (outside_dir / "latest_live_acceptance_readiness.json").write_text("{}", encoding="utf-8")
            outside_summary = json.loads(json.dumps(path_checked_summary))
            outside_summary["repository_cleanliness"]["json_path"] = str(outside_dir / "repository_cleanliness_payload.json")
            outside_summary["windows_package_preflight"]["json_path"] = "../outside/windows_package_preflight.json"
            outside_summary["client_delivery"]["json_path"] = "../outside/client_delivery.json"
            outside_summary["final_acceptance_gate"]["json_path"] = "../outside/final_acceptance_gate.json"
            outside_summary["issue_closure"]["json_path"] = "../outside/issue_closure_payload.json"
            outside_summary["authorization_handoff"]["json_path"] = "../outside/authorization_handoff_payload.json"
            outside_summary["authorization_handoff"]["readiness_report_path"] = "../outside/latest_live_acceptance_readiness.md"
            outside_summary["authorization_handoff"]["readiness_json_path"] = "../outside/latest_live_acceptance_readiness.json"
            outside_report_file = verify_reachops_acceptance_summary(outside_summary, summary_path=summary_path)
            self.assertFalse(outside_report_file["passed"])
            self.assertIn("repository_cleanliness_json_outside_summary_dir", outside_report_file["failures"])
            self.assertIn("windows_package_preflight_json_outside_summary_dir", outside_report_file["failures"])
            self.assertIn("client_delivery_json_outside_summary_dir", outside_report_file["failures"])
            self.assertIn("final_acceptance_gate_json_outside_summary_dir", outside_report_file["failures"])
            self.assertIn("issue_closure_json_outside_summary_dir", outside_report_file["failures"])
            self.assertIn("authorization_handoff_json_outside_summary_dir", outside_report_file["failures"])
            self.assertIn("authorization_handoff_readiness_report_outside_summary_dir", outside_report_file["failures"])
            self.assertIn("authorization_handoff_readiness_json_outside_summary_dir", outside_report_file["failures"])
            self.assertFalse(outside_report_file["repository_cleanliness"]["json_inside_summary_dir"])
            self.assertFalse(outside_report_file["windows_package_preflight"]["json_inside_summary_dir"])
            self.assertFalse(outside_report_file["client_delivery"]["json_inside_summary_dir"])
            self.assertFalse(outside_report_file["final_acceptance_gate"]["json_inside_summary_dir"])
            self.assertFalse(outside_report_file["issue_closure"]["json_inside_summary_dir"])
            self.assertFalse(outside_report_file["authorization_handoff"]["json_inside_summary_dir"])
            self.assertFalse(outside_report_file["authorization_handoff"]["readiness_report_inside_summary_dir"])
            self.assertFalse(outside_report_file["authorization_handoff"]["readiness_json_inside_summary_dir"])

        missing_readiness_summary = json.loads(json.dumps(passed_summary))
        missing_readiness_summary["live_readiness"] = {"status": "skipped", "ready": False, "no_submit": True}
        missing_readiness = verify_reachops_acceptance_summary(missing_readiness_summary, allow_external_pending=True)
        self.assertFalse(missing_readiness["passed"])
        self.assertIn("live_readiness_not_ready", missing_readiness["failures"])

        missing_preflight_summary = json.loads(json.dumps(passed_summary))
        missing_preflight_summary["live_preflight"] = {"status": "skipped"}
        missing_preflight = verify_reachops_acceptance_summary(missing_preflight_summary, allow_external_pending=True)
        self.assertFalse(missing_preflight["passed"])
        self.assertIn("live_preflight_not_completed", missing_preflight["failures"])

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

        wrong_executor_summary = json.loads(json.dumps(passed_summary))
        wrong_executor_summary["live_submit"]["executor_mode"] = "fixture"
        wrong_executor = verify_reachops_acceptance_summary(wrong_executor_summary, allow_external_pending=True)
        self.assertFalse(wrong_executor["passed"])
        self.assertIn("live_submit_executor_not_platform_selenium", wrong_executor["failures"])

        missing_execution_summary = json.loads(json.dumps(passed_summary))
        missing_execution_summary["live_submit"]["summary"]["success"] = 2
        missing_execution_summary["live_submit"]["summary"]["results"] = [
            {"action_type": "comment_reply", "status": "success"},
            {"action_type": "follow_review", "status": "success"},
        ]
        missing_execution = verify_reachops_acceptance_summary(missing_execution_summary, allow_external_pending=True)
        self.assertFalse(missing_execution["passed"])
        self.assertIn("live_submit_execution_summary_invalid", missing_execution["failures"])

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

        stale_sidecar_summary = json.loads(json.dumps(passed_summary))
        stale_sidecar_summary["live_submit"]["evidence_file_details"]["comment_reply"][0]["sidecar"]["action_id"] = "comment_reply-old"
        stale_sidecar = verify_reachops_acceptance_summary(stale_sidecar_summary, allow_external_pending=True)
        self.assertFalse(stale_sidecar["passed"])
        self.assertIn("live_submit_evidence_file_details_invalid", stale_sidecar["failures"])

        missing_result_identity_summary = json.loads(json.dumps(passed_summary))
        for row in missing_result_identity_summary["live_submit"]["summary"]["results"]:
            row.pop("action_id", None)
            row.pop("profile_id", None)
        missing_result_identity = verify_reachops_acceptance_summary(missing_result_identity_summary, allow_external_pending=True)
        self.assertFalse(missing_result_identity["passed"])
        self.assertIn("live_submit_evidence_file_details_invalid", missing_result_identity["failures"])

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

        evidenced_preflight_summary = json.loads(json.dumps(failed_preflight_summary))
        evidenced_preflight_summary["live_preflight"]["no_submit"] = True
        evidenced_preflight_summary["live_preflight"]["evidence_file_details"] = {
            "dm_review": [
                {
                    "path": "reports/reachops_live_preflight/evidence/dm.json",
                    "size": 123,
                    "sha256": hashlib.sha256(b"preflight failure").hexdigest(),
                    "action_type": "dm_review",
                    "profile_id": "27273",
                    "status": "failed",
                    "error_code": "PROFILE_START_FAILED",
                    "screenshot_available": False,
                }
            ]
        }
        evidenced_preflight_summary["live_preflight"]["environment_diagnostics"] = {
            "status": "blocked",
            "blocking_stage": "ixbrowser_open_profile",
            "configured_profile_ids": ["27273", "27240"],
            "attempted_profile_ids": ["27273", "27240"],
            "ready_profile_ids": [],
            "failed_profile_ids": ["27273", "27240"],
            "classification_counts": {"socks5_auth_failed": 2, "proxy_detection_failed": 2},
            "next_required_actions": ["Fix ixBrowser profile proxy credentials and pass ixBrowser proxy detection."],
        }
        evidenced_preflight_summary["pending_external_validation"] = [
            "授权允许时能真实执行",
            "真实 TikTok 平台提交",
            "客户端交付验收门禁不会把环境阻断当通过",
        ]
        evidenced_preflight = verify_reachops_acceptance_summary(evidenced_preflight_summary, allow_external_pending=True)
        self.assertTrue(evidenced_preflight["passed"])
        self.assertIn("live_preflight_environment_validation", evidenced_preflight["pending"])
        self.assertIn("dm_review", evidenced_preflight["live_preflight"]["evidence_file_detail_action_types"])
        self.assertEqual(evidenced_preflight["live_preflight"]["environment"]["blocking_stage"], "ixbrowser_open_profile")
        self.assertEqual(evidenced_preflight["live_preflight"]["environment"]["classification_counts"]["socks5_auth_failed"], 2)

        blocker_report = build_reachops_live_environment_blocker_report(
            evidenced_preflight_summary,
            "reports/reachops_acceptance/current/acceptance_summary.json",
            {
                "status": "passed",
                "passed": True,
                "final_delivery_ready": False,
                "bootstrap_only": True,
                "not_final_delivery_reasons": ["allow_missing_final_gate is bootstrap-only"],
            },
        )
        self.assertEqual(blocker_report["status"], "blocked")
        self.assertEqual(blocker_report["milestone3_status"], "blocked")
        self.assertEqual(blocker_report["milestone4_status"], "blocked")
        self.assertEqual(blocker_report["blocking_stage"], "ixbrowser_open_profile")
        self.assertEqual(blocker_report["classification_counts"]["socks5_auth_failed"], 2)
        self.assertEqual(blocker_report["failed_profile_ids"], ["27273", "27240"])
        self.assertTrue(blocker_report["no_submit"])
        self.assertIn("客户端交付验收门禁不会把环境阻断当通过", blocker_report["pending_external_validation"])
        self.assertIn("Rerun client delivery acceptance until acceptance_ready=true and readiness=pass.", blocker_report["pending_external_actions"])
        self.assertIn("background_acceptance_no_submit", blocker_report["safe_rerun_commands"])
        self.assertIn("ixbrowser_profile_environment", {row["scope"] for row in blocker_report["blockers"]})
        self.assertIn("final_delivery_package", {row["scope"] for row in blocker_report["blockers"]})
        self.assertIn("final_delivery_gate", {row["scope"] for row in blocker_report["blockers"]})
        self.assertEqual(blocker_report["final_acceptance_gate"]["status"], "")
        self.assertFalse(blocker_report["delivery_package"]["final_delivery_ready"])
        self.assertTrue(blocker_report["delivery_package"]["bootstrap_only"])
        self.assertFalse(blocker_report["delivery_package"]["final_gate_summary_ready"])

        weak_package_blocker_report = build_reachops_live_environment_blocker_report(
            evidenced_preflight_summary,
            "reports/reachops_acceptance/current/acceptance_summary.json",
            {
                "status": "passed",
                "passed": True,
                "final_delivery_ready": True,
                "bootstrap_only": False,
                "failures": [],
            },
        )
        self.assertEqual(weak_package_blocker_report["status"], "blocked")
        self.assertFalse(weak_package_blocker_report["delivery_package"]["final_gate_summary_ready"])
        self.assertIn("final_delivery_package", {row["scope"] for row in weak_package_blocker_report["blockers"]})
        final_delivery_package = [
            row for row in weak_package_blocker_report["blockers"] if row["scope"] == "final_delivery_package"
        ][0]
        self.assertFalse(final_delivery_package["final_gate_summary_ready"])

        weak_inner_evidence_package = final_package_check_payload()
        weak_inner_evidence_package["artifacts"]["installer"]["size"] = 0
        weak_inner_evidence_package["report_files"]["authorization_handoff"]["exists"] = False
        weak_inner_evidence_package["acceptance_verification"] = {"passed": False, "failures": ["live_submit_missing"], "pending": []}
        weak_inner_evidence_report = build_reachops_live_environment_blocker_report(
            evidenced_preflight_summary,
            "reports/reachops_acceptance/current/acceptance_summary.json",
            weak_inner_evidence_package,
        )
        self.assertEqual(weak_inner_evidence_report["status"], "blocked")
        self.assertFalse(weak_inner_evidence_report["delivery_package"]["artifacts_ready"])
        self.assertFalse(weak_inner_evidence_report["delivery_package"]["report_files_ready"])
        self.assertFalse(weak_inner_evidence_report["delivery_package"]["acceptance_verification_ready"])
        weak_inner_package_blocker = [
            row for row in weak_inner_evidence_report["blockers"] if row["scope"] == "final_delivery_package"
        ][0]
        self.assertFalse(weak_inner_package_blocker["artifacts_ready"])
        self.assertFalse(weak_inner_package_blocker["report_files_ready"])
        self.assertFalse(weak_inner_package_blocker["acceptance_verification_ready"])

        stale_goal_summary = json.loads(json.dumps(passed_summary))
        stale_goal_summary["goal_status"]["status"] = "ready_for_external_validation"
        stale_goal_summary["goal_status"]["pending_external_validation"] = ["真实 TikTok 平台提交"]
        stale_goal = verify_reachops_acceptance_summary(stale_goal_summary, allow_external_pending=True)
        self.assertFalse(stale_goal["passed"])
        self.assertIn("goal_status_not_passed", stale_goal["failures"])
        self.assertIn("goal_status_has_stale_pending", stale_goal["failures"])

    def test_reachops_live_environment_blocker_report_missing_summary_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "missing" / "acceptance_summary.json"
            with patch("builtins.print") as fake_print:
                code = reachops_live_environment_blocker_main(["--acceptance-summary", str(missing_path), "--json"])
            self.assertEqual(code, 2)
            payload = json.loads(fake_print.call_args[0][0])
            self.assertEqual(payload["status"], "missing")

    def test_ixbrowser_profile_metadata_report_is_readonly_and_redacts_proxy_secrets(self):
        class FakeIXClient:
            def __init__(self):
                self.open_profile_called = False

            def get_group_list(self, page=1, limit=100):
                if page > 1:
                    return []
                return [{"id": 286343, "title": "BR"}, {"id": 281726, "title": "Canada"}]

            def get_profile_list(self, page=1, limit=100, profile_id=0):
                if page > 1:
                    return []
                rows = [
                    {
                        "profile_id": 27273,
                        "name": "acct@example.com",
                        "site_url": "https://www.tiktok.com/",
                        "group_id": 286343,
                        "group_name": "BR",
                        "proxy_mode": 2,
                        "proxy_id": 33604959,
                        "proxy_type": "socks5",
                        "proxy_ip": "107.151.249.39",
                        "proxy_port": "3754",
                        "real_ip": "179.157.219.17",
                        "username": "hidden-user",
                        "password": "hidden-password",
                    },
                    {
                        "profile_id": 27240,
                        "name": "other@example.com",
                        "group_id": 281726,
                        "group_name": "Canada",
                        "proxy_id": 123,
                        "proxy_type": "http",
                    },
                ]
                if profile_id:
                    return [row for row in rows if int(row["profile_id"]) == int(profile_id)]
                return rows

            def get_proxy_list(self, page=1, limit=100, id=0):
                if page > 1:
                    return []
                rows = [
                    {
                        "id": 33604959,
                        "proxy_type": "socks5",
                        "proxy_ip": "107.151.249.39",
                        "proxy_port": "3754",
                        "proxy_user": "secret-user",
                        "proxy_password": "secret-password",
                        "country": "BR",
                    }
                ]
                if id:
                    return [row for row in rows if int(row["id"]) == int(id)]
                return rows

            def open_profile(self, *_args, **_kwargs):
                self.open_profile_called = True
                raise AssertionError("metadata report must not open profiles")

        client = FakeIXClient()
        report = build_ixbrowser_profile_metadata_report(client=client, profile_ids=["27273", "missing"])
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["safe_read_only"])
        self.assertFalse(report["open_profile_called"])
        self.assertFalse(client.open_profile_called)
        self.assertEqual(report["missing_profile_ids"], ["missing"])
        self.assertEqual(report["selected_profile_count"], 1)
        self.assertEqual(report["selected_profiles"][0]["profile"]["profile_id"], 27273)
        self.assertEqual(report["selected_profiles"][0]["proxy"]["proxy_user"], "***redacted***")
        self.assertEqual(report["selected_profiles"][0]["proxy"]["proxy_password"], "***redacted***")
        self.assertNotIn("secret-user", json.dumps(report))
        self.assertEqual(report["proxy_type_counts"]["socks5"], 1)

    def test_ixbrowser_profile_metadata_report_syncs_selected_group_count_into_group_list(self):
        class FakeIXClient:
            def get_group_list(self, page=1, limit=100):
                if page > 1:
                    return []
                return [{"id": 257999, "title": "United States", "count": 0}, {"id": 281726, "title": "Canada", "count": 0}]

            def get_profile_list(self, page=1, limit=100, group_id=0, profile_id=0):
                assert int(group_id or 0) == 257999
                if page > 1:
                    return []
                return [
                    {"profile_id": 1, "group_id": 257999, "group_name": "United States", "proxy_id": ""},
                    {"profile_id": 2, "group_id": 257999, "group_name": "United States", "proxy_id": ""},
                ]

            def get_proxy_list(self, page=1, limit=100, id=0):
                return []

        with patch("ReachOps.workbench.standalone_app.load_ixbrowser_group_profile_count", return_value=702):
            report = build_ixbrowser_profile_metadata_report(client=FakeIXClient(), group_name="United States")

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["selected_profile_count"], 702)
        groups = {row["group_name"]: row for row in report["groups"]}
        self.assertEqual(groups["United States"]["profile_count"], 702)
        self.assertTrue(groups["United States"]["count_known"])
        self.assertEqual(groups["United States"]["count_source"], "selected_group_profile_list")
        self.assertEqual(groups["Canada"]["profile_count"], 0)

    def test_reachops_windows_package_preflight_validates_build_inputs_without_claiming_final_delivery(self):
        report = build_reachops_windows_package_preflight()

        self.assertEqual(report["status"], "ready_for_windows_build")
        self.assertTrue(report["ready_for_windows_build"])
        self.assertFalse(report["final_delivery_ready"])
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["files"]["windows_build_script"]["exists"])
        self.assertTrue(report["files"]["ci_release_baseline_audit"]["exists"])
        self.assertTrue(report["files"]["account_readiness_audit"]["exists"])
        self.assertTrue(report["files"]["control_plane_audit"]["exists"])
        self.assertTrue(report["files"]["pyinstaller_spec"]["exists"])
        self.assertTrue(report["files"]["inno_setup_script"]["exists"])
        self.assertTrue(report["files"]["acceptance_inputs_template"]["exists"])
        self.assertTrue(report["files"]["live_acceptance_status"]["exists"])
        self.assertTrue(report["files"]["authorization_handoff_bundle"]["exists"])
        self.assertTrue(report["files"]["start_contract_audit"]["exists"])
        self.assertTrue(report["contract_checks"]["tools/build_reachops_windows.ps1"]["ok"])
        self.assertTrue(report["contract_checks"]["tools/reachops_ci_release_baseline_audit.py"]["ok"])
        self.assertTrue(report["contract_checks"]["tools/reachops_account_readiness_audit.py"]["ok"])
        self.assertTrue(report["contract_checks"]["tools/reachops_control_plane_audit.py"]["ok"])
        self.assertTrue(report["contract_checks"]["tools/run_reachops_acceptance_windows.ps1"]["ok"])
        self.assertTrue(report["contract_checks"]["tools/reachops_start_contract_audit.py"]["ok"])
        self.assertTrue(report["build_contract"]["default_build_requires_installer"])
        self.assertTrue(report["build_contract"]["skip_installer_is_non_final"])
        self.assertTrue(report["build_contract"]["preflight_report_path"].endswith("windows_package_preflight.json"))
        self.assertIn("exe", report["missing_final_artifacts"])
        self.assertIn("installer", report["missing_final_artifacts"])
        self.assertIn("acceptance_summary", report["missing_final_artifacts"])

    def test_reachops_goal_delivery_report_summarizes_pm_boundary(self):
        start_contract = {
            "target_planned": True,
            "campaign_started": True,
            "profile_preflight_checked": True,
            "collection_done": True,
            "action_terminal_or_no_submit_reason": True,
        }
        remediation_plan = {
            "artifact_actions": ["exe", "installer", "manifest", "acceptance_summary"],
            "commands": [
                r"powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1",
                r"powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
                r"python tools\reachops_authorization_handoff_bundle.py --verify",
                r"python tools\reachops_final_acceptance_gate.py --json",
            ],
        }

        def section(payload, returncode=0):
            return {"command": "fixture", "returncode": returncode, "stderr": "", "payload": payload}

        def fake_command_payload(command, timeout=120):
            script = " ".join(command)
            if "reachops_mvp_acceptance_summary.py" in script:
                return section(
                    {
                        "status": "mvp_accepted_external_pending",
                        "mvp_local_ready": True,
                        "failed_checks": [],
                        "client_delivery": {
                            "operation_counts": {"candidates": 4, "actions": 0},
                            "no_action_reason": {"code": "preflight_only", "message": "默认预检不提交。"},
                        },
                        "checks": {"start_contract_evidence_complete": True},
                        "start_contract_evidence": start_contract,
                        "evidence_files": {"mvp_acceptance_summary": "/tmp/latest_mvp_acceptance_summary.json"},
                    }
                )
            if "reachops_mac_loop_acceptance.py" in script:
                return section(
                    {
                        "status": "passed",
                        "mac_loop_ready": True,
                        "checks": {"start_contract_evidence_complete": True},
                        "start_contract_evidence": start_contract,
                        "operations": {
                            "candidates": 4,
                            "actions": 0,
                            "touch_success": 0,
                            "touch_failed": 0,
                            "no_action_reason": {"code": "preflight_only", "message": "默认预检不提交。"},
                        },
                        "latest_batch": {"id": "fixture_batch", "profile_group": "United States"},
                        "groups": {"live_all_group_counts_known": True},
                    }
                )
            if "reachops_client_delivery_check.py" in script:
                return section(
                    {
                        "status": "passed",
                        "readiness": "pass",
                        "contract_ok": True,
                        "acceptance_ready": True,
                        "final_delivery_ready": True,
                        "failed_checks": [],
                        "blockers": [],
                        "operation_counts": {"candidates": 4, "actions": 0},
                        "no_action_reason": {"code": "preflight_only", "message": "默认预检不提交。"},
                        "delivery_check_path": "/tmp/latest_delivery_check.json",
                        "start_contract_evidence": start_contract,
                        "checks": {"start_contract_evidence_complete": True},
                    }
                )
            if "reachops_windows_package_preflight.py" in script:
                return section(
                    {
                        "status": "ready_for_windows_build",
                        "ready_for_windows_build": True,
                        "failures": [],
                        "missing_final_artifacts": ["exe", "installer", "manifest", "acceptance_summary"],
                        "build_contract": {"preflight_report_path": "/tmp/windows_package_preflight.json"},
                    }
                )
            if "reachops_issue_closure_audit.py" in script:
                return section(
                    {
                        "schema_version": "reachops.issue_closure_audit.v1",
                        "status": "passed_with_external_acceptance_pending",
                        "passed": True,
                        "github_issues": {"closure_requires_external_validation": True},
                        "summary": {
                            "issues_total": 7,
                            "local_contracts_passed": 7,
                            "acceptance_criteria_total": 53,
                            "acceptance_criteria_local_passed": 36,
                            "acceptance_criteria_external_pending": 17,
                            "acceptance_criteria_unclassified": 0,
                            "external_pending_count": 36,
                        },
                        "external_acceptance_pending": ["issue_3_100_real_no_submit_runs_three_industries"],
                    }
                )
            if "reachops_delivery_package_check.py" in script:
                return section(
                    {
                        "status": "failed",
                        "final_delivery_ready": False,
                        "missing_artifacts": ["exe", "installer", "manifest", "acceptance_summary"],
                        "remediation_plan": remediation_plan,
                    },
                    returncode=1,
                )
            if "reachops_final_acceptance_gate.py" in script:
                return section(
                    {
                        "status": "failed",
                        "final_delivery_ready": False,
                        "failed_checks": ["delivery_package:passed"],
                        "checks": [
                            {
                                "name": "goal_status:passed",
                                "ok": False,
                                "evidence": {"pending_external_validation": ["authorized_live_submit"]},
                            }
                        ],
                        "final_delivery_blockers": [
                            {
                                "scope": "external_authorized_execution",
                                "status": "ready_for_external_validation",
                                "required_evidence": ["授权 TikTok 目标", "comment_visible_confirmed=true"],
                            },
                            {
                                "scope": "windows_final_artifacts",
                                "status": "failed",
                                "required_artifacts": ["exe", "installer", "manifest", "acceptance_summary"],
                            },
                        ],
                    },
                    returncode=1,
                )
            if "reachops_repository_cleanliness_check.py" in script:
                return section({"status": "passed", "passed": True, "forbidden_count": 0})
            return section({})

        with patch("tools.reachops_goal_delivery_runner.command_payload", side_effect=fake_command_payload):
            report = build_reachops_goal_delivery_report()

        self.assertEqual(report["product"], "ReachOps")
        mvp = (report["sections"]["mvp_acceptance"] or {}).get("payload") or {}
        mac_loop = (report["sections"]["mac_loop_acceptance"] or {}).get("payload") or {}
        client = (report["sections"]["client_delivery"] or {}).get("payload") or {}
        clean = (report["sections"]["repository_cleanliness"] or {}).get("payload") or {}
        expected_local_ready = (
            bool(mvp.get("mvp_local_ready"))
            and bool(mac_loop.get("mac_loop_ready"))
            and str(client.get("status") or "") == "passed"
            and bool(client.get("final_delivery_ready"))
            and bool(clean.get("passed"))
        )
        self.assertIn(report["status"], {"not_ready", "local_mvp_accepted_final_pending", "final_delivery_ready"})
        self.assertEqual(report["local_mvp_ready"], expected_local_ready)
        self.assertTrue(report["windows_build_ready"])
        self.assertFalse(report["final_delivery_ready"])
        scopes = {row["scope"] for row in report["blockers"]}
        if not report["local_mvp_ready"]:
            self.assertIn("local_mvp", scopes)
        self.assertIn("windows_final_artifacts", scopes)
        self.assertIn("external_authorized_execution", scopes)
        self.assertIn("commercial_issue_closure", scopes)
        final_blockers = {row["scope"]: row for row in report["final_delivery_blockers"]}
        self.assertIn("windows_final_artifacts", final_blockers)
        self.assertIn("external_authorized_execution", final_blockers)
        self.assertIn("required_artifacts", final_blockers["windows_final_artifacts"])
        self.assertIn("required_evidence", final_blockers["external_authorized_execution"])
        windows_blocker = next(row for row in report["blockers"] if row["scope"] == "windows_final_artifacts")
        remediation = windows_blocker["remediation_plan"]
        self.assertIn("exe", remediation["artifact_actions"])
        self.assertIn("acceptance_summary", remediation["artifact_actions"])
        self.assertIn("tools\\build_reachops_windows.ps1", "\n".join(remediation["commands"]))
        self.assertIn("tools\\reachops_final_acceptance_gate.py --json", "\n".join(remediation["commands"]))
        self.assertIn("mvp_acceptance", report["sections"])
        self.assertIn("mac_loop_acceptance", report["sections"])
        self.assertIn("windows_package_preflight", report["sections"])
        self.assertIn("issue_closure", report["sections"])
        self.assertIn("final_gate", report["sections"])
        windows_deliverable = next(row for row in report["deliverables"] if row["name"] == "Windows 最终交付包")
        self.assertIn("issue_closure_payload", windows_deliverable["acceptance"])
        local_evidence = report["local_mvp_evidence"]
        self.assertIn("operation_counts", local_evidence)
        self.assertIn("no_action_reason", local_evidence)
        self.assertTrue(local_evidence["start_contract_evidence_complete"])
        self.assertTrue(local_evidence["start_contract_evidence"]["target_planned"])
        self.assertTrue(local_evidence["start_contract_evidence"]["campaign_started"])
        self.assertTrue(local_evidence["start_contract_evidence"]["profile_preflight_checked"])
        self.assertTrue(local_evidence["start_contract_evidence"]["collection_done"])
        self.assertTrue(local_evidence["start_contract_evidence"]["action_terminal_or_no_submit_reason"])
        if int((local_evidence["operation_counts"] or {}).get("actions") or 0) == 0:
            self.assertTrue(local_evidence["no_action_reason_present_when_no_actions"])
            self.assertTrue(str((local_evidence["no_action_reason"] or {}).get("code") or ""))
        self.assertEqual(report["execution_contract"]["mode"], "local_pm_goal_gate")
        self.assertTrue(report["execution_contract"]["does_not_submit"])
        self.assertTrue(report["execution_contract"]["does_not_open_browser_profile"])
        self.assertTrue(report["execution_contract"]["operator_summary"].endswith("latest_goal_delivery_summary.md"))
        self.assertIn("ready_conditions", report["start_acquisition_contract"])
        self.assertTrue(any("ixBrowser Local API" in row for row in report["start_acquisition_contract"]["ready_conditions"]))
        self.assertIn("preflight", report["outreach_effectiveness_contract"]["modes"])
        self.assertFalse(report["outreach_effectiveness_contract"]["modes"]["preflight"]["submits_to_platform"])
        self.assertTrue(report["outreach_effectiveness_contract"]["modes"]["live_comment"]["submits_to_platform"])
        deliverables = {row["name"]: row for row in report["deliverables"]}
        self.assertIn("Web 运营面板", deliverables)
        self.assertIn("Mac 本地自动循环验收", deliverables)
        self.assertIn("Mac 本地 MVP 验收交付单", deliverables)
        self.assertIn("Windows 最终交付包", deliverables)
        self.assertIn("目标模式 PM 摘要", deliverables)
        self.assertEqual(deliverables["Mac 本地 MVP 验收交付单"]["required_for"], "local_mvp")
        self.assertEqual(deliverables["Windows 最终交付包"]["required_for"], "final_delivery")
        self.assertIn("local_mvp", report["acceptance_standards"])
        self.assertIn("final_delivery", report["acceptance_standards"])
        self.assertTrue(any("真实 TikTok 提交" in row for row in report["acceptance_standards"]["final_delivery"]))
        self.assertTrue(any("authorization_handoff" in row for row in report["acceptance_standards"]["final_delivery"]))
        self.assertIn("authorization_handoff", deliverables["Windows 最终交付包"]["acceptance"])
        self.assertTrue(report["evidence_files"]["goal_delivery_summary"].endswith("latest_goal_delivery_summary.md"))
        self.assertTrue(report["evidence_files"]["pm_delivery_baseline"].endswith("REACHOPS_PM_DELIVERY_BASELINE.md"))
        self.assertTrue(report["evidence_files"]["mac_local_mvp_acceptance"].endswith("REACHOPS_MAC_LOCAL_MVP_ACCEPTANCE.md"))
        self.assertTrue(report["evidence_files"]["live_acceptance_readiness"].endswith("latest_live_acceptance_readiness.md"))
        self.assertTrue(report["evidence_files"]["live_acceptance_readiness_json"].endswith("latest_live_acceptance_readiness.json"))
        self.assertTrue(report["evidence_files"]["authorization_handoff_bundle"].endswith("latest_reachops_authorization_handoff.zip"))
        self.assertTrue(report["evidence_files"]["mac_loop_acceptance"].endswith("reachops_mac_loop_acceptance.py"))
        boundary = report["delivery_boundary"]
        self.assertEqual(boundary["local_mvp_scope_ready"], report["local_mvp_ready"])
        self.assertTrue(boundary["client_gate_scope_ready"])
        self.assertTrue(boundary["windows_build_input_scope_ready"])
        self.assertFalse(boundary["overall_final_delivery_scope_ready"])
        self.assertTrue(boundary["client_gate_final_delivery_ready_is_not_overall_final_delivery"])
        self.assertIn("windows_final_artifacts", boundary["blocking_scopes"])
        self.assertIn("external_authorized_execution", boundary["blocking_scopes"])
        index = report["deliverable_index"]
        self.assertEqual(index["web_operator_panel"]["ready"], report["local_mvp_ready"])
        self.assertEqual(index["local_mvp_acceptance"]["ready"], report["local_mvp_ready"])
        self.assertTrue(index["windows_build_inputs"]["ready"])
        self.assertFalse(index["windows_final_package"]["ready"])
        self.assertFalse(index["final_acceptance_gate"]["ready"])
        self.assertFalse(index["authorized_live_submit"]["ready"])
        self.assertFalse(index["commercial_issue_closure"]["ready"])
        self.assertEqual(index["commercial_issue_closure"]["blocking_scope"], "commercial_issue_closure")
        self.assertEqual(index["commercial_issue_closure"]["acceptance_criteria_total"], 53)
        self.assertEqual(index["commercial_issue_closure"]["acceptance_criteria_external_pending"], 17)
        self.assertEqual(index["windows_final_package"]["blocking_scope"], "windows_final_artifacts")
        self.assertIn("exe", index["windows_final_package"]["missing_artifacts"])
        self.assertIn("acceptance_summary", index["windows_final_package"]["missing_artifacts"])
        self.assertIn("tools\\build_reachops_windows.ps1", "\n".join(index["windows_final_package"]["remediation_plan"]["commands"]))
        self.assertIn("tools\\reachops_authorization_handoff_bundle.py --verify", "\n".join(index["windows_final_package"]["remediation_plan"]["commands"]))
        markdown = render_reachops_goal_delivery_summary(report)
        self.assertIn("# ReachOps 目标模式验收摘要", markdown)
        self.assertIn("delivery_boundary.overall_final_delivery_scope_ready=false", markdown)
        self.assertIn("## 开始获客合同", markdown)
        self.assertIn("## 有效触达定义", markdown)
        self.assertIn("## 本地 MVP 证据", markdown)
        self.assertIn("无触达原因", markdown)
        self.assertIn("## 最终交付标准", markdown)
        self.assertIn("authorization_handoff", markdown)
        self.assertIn("`windows_final_package` | `false`", markdown)
        self.assertIn("`authorized_live_submit` | `false`", markdown)
        self.assertIn("`commercial_issue_closure` | `false`", markdown)
        self.assertIn("本地 MVP 可验收不等于最终客户交付完成", markdown)

    def test_reachops_goal_delivery_does_not_mark_live_submit_ready_without_final_gate_evidence(self):
        blockers = [{"scope": "external_authorized_execution", "status": "missing_final_gate_evidence"}]
        index = build_reachops_deliverable_index(
            local_ready=False,
            windows_build_ready=True,
            final_ready=False,
            mvp={"status": "blocked_by_accounts", "failed_checks": ["client_delivery:acceptance:ready"]},
            client={"failed_checks": ["acceptance:ready"]},
            windows_preflight={"status": "ready_for_windows_build", "ready_for_windows_build": True},
            package={"status": "failed", "missing_artifacts": ["exe"]},
            final_gate={},
            clean={"status": "passed", "passed": True},
            blockers=blockers,
            issue_closure={"status": "passed_with_external_acceptance_pending", "passed": True, "github_issues": {"closure_requires_external_validation": True}, "summary": {"acceptance_criteria_total": 53, "acceptance_criteria_external_pending": 17, "acceptance_criteria_unclassified": 0, "external_pending_count": 36}},
        )
        boundary = build_reachops_delivery_boundary(
            local_ready=False,
            windows_build_ready=True,
            final_ready=False,
            client={"status": "blocked_by_accounts", "acceptance_ready": False, "final_delivery_ready": False},
            package={"status": "failed", "final_delivery_ready": False},
            goal_pending=[],
            authorized_live_ready=False,
            blockers=blockers,
        )

        self.assertFalse(index["authorized_live_submit"]["ready"])
        self.assertEqual(index["authorized_live_submit"]["blocking_scope"], "external_authorized_execution")
        self.assertFalse(index["commercial_issue_closure"]["ready"])
        self.assertEqual(index["commercial_issue_closure"]["blocking_scope"], "commercial_issue_closure")
        self.assertFalse(boundary["external_authorized_execution_ready"])

    def test_reachops_web_ui_fallback_evidence_plan_exposes_issue_closure(self):
        from tools import reachops_web_ui

        plan = reachops_web_ui.fallback_final_delivery_evidence_plan(
            [{"scope": "commercial_issue_closure", "status": "passed_with_external_acceptance_pending"}]
        )

        self.assertFalse(plan["ready"])
        self.assertEqual(plan["pending_scopes"], ["commercial_issue_closure"])
        item = plan["items"][0]
        self.assertEqual(item["title"], "Issues #1-#7 商业交付闭环证据")
        self.assertIn("python tools\\reachops_issue_closure_audit.py --json", item["commands"])
        self.assertIn("issue_closure.summary.acceptance_criteria_external_pending=0", item["proof_fields"])
        self.assertIn("issue_closure.github_issues.closure_requires_external_validation=false", item["proof_fields"])

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
            exe.write_bytes(minimal_windows_pe_bytes(b"reachops exe"))
            installer.write_bytes(minimal_windows_pe_bytes(b"reachops installer"))
            manifest = build_manifest(installer, version="0.4.0", build="mvp-001", channel="mvp")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            for name in [
                "delivery_audit_payload.json",
                "operator_pressure_payload.json",
                "installer_smoke_payload.json",
                "ui_startup_payload.json",
                "activation_status_payload.json",
                "live_acceptance_status_payload.json",
                "authorization_handoff_payload.json",
                "live_validation_manifest.json",
                "repository_cleanliness_payload.json",
                "windows_package_preflight.json",
                "client_delivery.json",
                "live_readiness_payload.json",
                "live_preflight_payload.json",
                "live_submit_payload.json",
                "goal_status_report.json",
                "latest_live_acceptance_readiness.md",
                "latest_live_acceptance_readiness.json",
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
                    "pending_external_validation": 3,
                    "resolved_external_validation": 3,
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
                "activation_status": {
                    "status": "ready",
                    "ready": True,
                    "no_browser_started": True,
                    "no_submit": True,
                    "activation_status_exists": True,
                    "current_device_id": "device-a",
                    "json_path": str(report_dir / "activation_status_payload.json"),
                },
                "live_acceptance_status": {
                    "status": "passed",
                    "ready_for_live_preflight": True,
                    "ready_for_live_submit": True,
                    "final_delivery_ready": True,
                    "no_browser_started": True,
                    "no_submit": True,
                    "failed_checks": [],
                    "local_inputs": {"usable": True},
                    "activation": {"ready": True},
                    "live_validation": {
                        "missing_inputs": [],
                        "selected_profile_ids": ["profile-a"],
                    },
                    "next_required_actions": [],
                    "json_path": str(report_dir / "live_acceptance_status_payload.json"),
                },
                "authorization_handoff": {
                    "status": "created",
                    "exists": True,
                    "final_delivery_ready": False,
                    "no_browser_started": True,
                    "no_submit": True,
                    "bundle_path": str(report_dir / "latest_reachops_authorization_handoff.zip"),
                    "readiness_status": "passed",
                    "readiness_report_path": str(report_dir / "latest_live_acceptance_readiness.md"),
                    "readiness_json_path": str(report_dir / "latest_live_acceptance_readiness.json"),
                    "json_path": str(report_dir / "authorization_handoff_payload.json"),
                },
                "live_validation": {
                    "status": "ready",
                    "no_browser_started": True,
                    "no_submit": True,
                    "json_path": str(report_dir / "live_validation_manifest.json"),
                },
                "repository_cleanliness": {
                    "status": "passed",
                    "passed": True,
                    "forbidden_count": 0,
                    "json_path": str(report_dir / "repository_cleanliness_payload.json"),
                },
                "windows_package_preflight": {
                    "status": "ready_for_windows_build",
                    "ready_for_windows_build": True,
                    "final_delivery_ready": False,
                    "build_contract": {
                        "default_build_requires_installer": True,
                        "skip_installer_is_non_final": True,
                    },
                    "json_path": str(report_dir / "windows_package_preflight.json"),
                },
                "client_delivery": {
                    "status": "passed",
                    "readiness": "pass",
                    "contract_ok": True,
                    "acceptance_ready": True,
                    "final_delivery_ready": True,
                    "failed_checks": [],
                    "json_path": str(report_dir / "client_delivery.json"),
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
                    "passed": True,
                    "live_submit": True,
                    "activation_status_loaded": True,
                    "activation_status_source": "C:/ReachOps/config/reachops_activation_status.json",
                    "summary": {
                        "selected_actions": 3,
                        "success": 3,
                        "failed": 0,
                        "skipped": 0,
                        "results": [
                            {"action_type": "comment_reply", "status": "success", "action_id": "comment_reply-1", "profile_id": "profile-a"},
                            {"action_type": "follow_review", "status": "success", "action_id": "follow_review-1", "profile_id": "profile-a"},
                            {"action_type": "dm_review", "status": "success", "action_id": "dm_review-1", "profile_id": "profile-a"},
                        ],
                    },
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
                "final_acceptance_gate": {
                    "status": "passed",
                    "final_delivery_ready": True,
                    "failed_checks": [],
                    "checks": final_acceptance_gate_payload()["checks"],
                    "json_path": str(report_dir / "final_acceptance_gate.json"),
                },
                "issue_closure": {
                    **final_issue_closure_payload(),
                    "json_path": str(report_dir / "issue_closure_payload.json"),
                },
            }
            (report_dir / "client_delivery.json").write_text(json.dumps(summary["client_delivery"]), encoding="utf-8")
            (report_dir / "issue_closure_payload.json").write_text(json.dumps(summary["issue_closure"]), encoding="utf-8")
            (report_dir / "final_acceptance_gate.json").write_text(json.dumps(summary["final_acceptance_gate"]), encoding="utf-8")
            acceptance_summary = report_dir / "acceptance_summary.json"
            acceptance_summary.write_text(json.dumps(summary), encoding="utf-8")

            result = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertTrue(result["passed"])
            self.assertEqual(result["status"], "passed")
            self.assertFalse(result["failures"])
            self.assertEqual(result["artifacts"]["manifest"]["actual_sha256"], result["artifacts"]["manifest"]["expected_sha256"])
            self.assertTrue(result["artifacts"]["exe"]["pe_signature_valid"])
            self.assertTrue(result["artifacts"]["exe"]["pe_dos_signature_valid"])
            self.assertTrue(result["artifacts"]["exe"]["pe_header_signature_valid"])
            self.assertTrue(result["artifacts"]["installer"]["pe_signature_valid"])
            self.assertTrue(result["artifacts"]["installer"]["pe_dos_signature_valid"])
            self.assertTrue(result["artifacts"]["installer"]["pe_header_signature_valid"])
            self.assertTrue(result["report_files"]["repository_cleanliness"]["exists"])
            self.assertTrue(result["report_files"]["windows_package_preflight"]["exists"])
            self.assertTrue(result["report_files"]["client_delivery"]["exists"])
            self.assertTrue(result["report_files"]["issue_closure"]["exists"])
            self.assertTrue(result["report_files"]["final_acceptance_gate"]["exists"])
            self.assertEqual(result["final_gate_report"]["status"], "passed")
            self.assertEqual(result["final_gate_report"]["missing_required_checks"], [])
            self.assertEqual(result["final_gate_report"]["failed_required_checks"], [])
            self.assertTrue(result["final_gate_report"]["checks_by_name"]["delivery_package:passed"]["ok"])

            bad_final_gate_payload = final_acceptance_gate_payload()
            bad_final_gate_payload["status"] = "not_ready"
            bad_final_gate_payload["final_delivery_ready"] = False
            bad_final_gate_payload["failed_checks"] = ["delivery_package:passed"]
            for row in bad_final_gate_payload["checks"]:
                if row["name"] == "delivery_package:passed":
                    row["ok"] = False
            invalid_final_gate = json.loads(json.dumps(summary))
            (report_dir / "final_acceptance_gate.json").write_text(
                json.dumps(bad_final_gate_payload),
                encoding="utf-8",
            )
            acceptance_summary.write_text(json.dumps(invalid_final_gate), encoding="utf-8")
            invalid_final_gate_result = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(invalid_final_gate_result["passed"])
            self.assertIn("final_acceptance_gate_json_not_passed", invalid_final_gate_result["failures"])
            self.assertIn("final_acceptance_gate_json_not_ready", invalid_final_gate_result["failures"])
            self.assertIn("final_acceptance_gate_json_failed_checks", invalid_final_gate_result["failures"])
            self.assertIn("final_acceptance_gate_json_checks_failed", invalid_final_gate_result["failures"])
            self.assertIn("final_acceptance_gate_json_mismatch", invalid_final_gate_result["failures"])
            self.assertEqual(invalid_final_gate_result["final_gate_report"]["failed_required_checks"], ["delivery_package:passed"])

            convergence_gate_payload = final_acceptance_gate_payload()
            convergence_gate_payload["status"] = "not_ready"
            convergence_gate_payload["final_delivery_ready"] = False
            convergence_gate_payload["failed_checks"] = ["delivery_package:passed"]
            for index, row in enumerate(convergence_gate_payload["checks"]):
                if row["name"] == "delivery_package:passed":
                    convergence_gate_payload["checks"][index] = {
                        "name": "delivery_package:passed",
                        "ok": False,
                        "status": "failed",
                        "evidence": {
                            "bootstrap_only": True,
                            "not_final_delivery_reasons": [
                                "allow_missing_final_gate is bootstrap-only; rerun without it after final_acceptance_gate.json is written."
                            ],
                        },
                    }
            convergence_summary = json.loads(json.dumps(summary))
            convergence_summary["final_acceptance_gate"] = convergence_gate_payload
            convergence_summary["final_acceptance_gate"]["json_path"] = str(report_dir / "final_acceptance_gate.json")
            (report_dir / "final_acceptance_gate.json").write_text(
                json.dumps(convergence_gate_payload),
                encoding="utf-8",
            )
            acceptance_summary.write_text(json.dumps(convergence_summary), encoding="utf-8")
            strict_convergence = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(strict_convergence["passed"])
            self.assertIn("final_acceptance_gate_json_not_passed", strict_convergence["failures"])
            convergence_result = check_reachops_delivery_package(
                root=root,
                acceptance_summary_path=acceptance_summary,
                allow_final_gate_convergence=True,
            )
            self.assertTrue(convergence_result["passed"])
            self.assertTrue(convergence_result["allow_final_gate_convergence"])
            self.assertTrue(convergence_result["final_gate_report"]["convergence_only"])
            self.assertEqual(convergence_result["final_gate_report"]["failed_required_checks"], ["delivery_package:passed"])
            (report_dir / "final_acceptance_gate.json").write_text(json.dumps(summary["final_acceptance_gate"]), encoding="utf-8")

            missing_checks_summary = json.loads(json.dumps(summary))
            missing_checks_summary["final_acceptance_gate"]["checks"] = []
            (report_dir / "final_acceptance_gate.json").write_text(json.dumps(missing_checks_summary["final_acceptance_gate"]), encoding="utf-8")
            acceptance_summary.write_text(json.dumps(missing_checks_summary), encoding="utf-8")
            missing_checks = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(missing_checks["passed"])
            self.assertIn("final_acceptance_gate_json_checks_missing", missing_checks["failures"])

            failed_check_summary = json.loads(json.dumps(summary))
            for row in failed_check_summary["final_acceptance_gate"]["checks"]:
                if row["name"] == "delivery_package:passed":
                    row["ok"] = False
            (report_dir / "final_acceptance_gate.json").write_text(json.dumps(failed_check_summary["final_acceptance_gate"]), encoding="utf-8")
            acceptance_summary.write_text(json.dumps(failed_check_summary), encoding="utf-8")
            failed_check = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(failed_check["passed"])
            self.assertIn("final_acceptance_gate_json_checks_failed", failed_check["failures"])
            (report_dir / "final_acceptance_gate.json").write_text(json.dumps(summary["final_acceptance_gate"]), encoding="utf-8")

            stale_issue_closure_summary = json.loads(json.dumps(summary))
            stale_issue_closure_summary["final_acceptance_gate"]["checks"] = [
                row
                for row in stale_issue_closure_summary["final_acceptance_gate"]["checks"]
                if row["name"] != "commercial_issue_closure:closed"
            ]
            (report_dir / "final_acceptance_gate.json").write_text(
                json.dumps(stale_issue_closure_summary["final_acceptance_gate"]),
                encoding="utf-8",
            )
            acceptance_summary.write_text(json.dumps(stale_issue_closure_summary), encoding="utf-8")
            stale_issue_closure = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(stale_issue_closure["passed"])
            self.assertIn("final_acceptance_gate_json_checks_missing", stale_issue_closure["failures"])
            self.assertEqual(
                stale_issue_closure["final_gate_report"]["missing_required_checks"],
                ["commercial_issue_closure:closed"],
            )
            (report_dir / "final_acceptance_gate.json").write_text(json.dumps(summary["final_acceptance_gate"]), encoding="utf-8")

            outside_report = root / "outside_live_submit_payload.json"
            outside_report.write_text("{}", encoding="utf-8")
            escaped_report_summary = json.loads(json.dumps(summary))
            escaped_report_summary["live_submit"]["json_path"] = str(outside_report)
            acceptance_summary.write_text(json.dumps(escaped_report_summary), encoding="utf-8")
            escaped_report = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(escaped_report["passed"])
            self.assertIn("live_submit_json_outside_acceptance_dir", escaped_report["failures"])

            missing_preflight_summary = json.loads(json.dumps(summary))
            missing_preflight_summary.pop("windows_package_preflight", None)
            acceptance_summary.write_text(json.dumps(missing_preflight_summary), encoding="utf-8")
            missing_preflight = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(missing_preflight["passed"])
            self.assertIn("windows_package_preflight_json_path_missing", missing_preflight["failures"])

            missing_final_gate_summary = json.loads(json.dumps(summary))
            missing_final_gate_summary.pop("final_acceptance_gate", None)
            acceptance_summary.write_text(json.dumps(missing_final_gate_summary), encoding="utf-8")
            missing_final_gate = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(missing_final_gate["passed"])
            self.assertIn("final_acceptance_gate_json_path_missing", missing_final_gate["failures"])
            bootstrap_missing_final_gate = check_reachops_delivery_package(
                root=root,
                acceptance_summary_path=acceptance_summary,
                allow_missing_final_gate=True,
            )
            self.assertTrue(bootstrap_missing_final_gate["passed"])
            self.assertFalse(bootstrap_missing_final_gate["final_delivery_ready"])
            self.assertTrue(bootstrap_missing_final_gate["bootstrap_only"])
            self.assertIn("allow_missing_final_gate", bootstrap_missing_final_gate["not_final_delivery_reasons"][0])
            self.assertTrue(bootstrap_missing_final_gate["allow_missing_final_gate"])

            broken_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            broken_manifest["installer"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(broken_manifest), encoding="utf-8")
            acceptance_summary.write_text(json.dumps(summary), encoding="utf-8")
            broken = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(broken["passed"])
            self.assertIn("manifest_sha256_mismatch", broken["failures"])

            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            exe.write_bytes(b"not a PE executable")
            invalid_exe = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(invalid_exe["passed"])
            self.assertIn("exe_not_windows_pe", invalid_exe["failures"])
            self.assertFalse(invalid_exe["artifacts"]["exe"]["pe_signature_valid"])
            exe.write_bytes(b"MZ" + b"\x00" * 128)
            dos_only_exe = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(dos_only_exe["passed"])
            self.assertIn("exe_not_windows_pe", dos_only_exe["failures"])
            self.assertTrue(dos_only_exe["artifacts"]["exe"]["pe_dos_signature_valid"])
            self.assertFalse(dos_only_exe["artifacts"]["exe"]["pe_header_signature_valid"])
            exe.write_bytes(minimal_windows_pe_bytes(b"reachops exe"))

            installer.write_bytes(b"not a PE installer")
            invalid_installer = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(invalid_installer["passed"])
            self.assertIn("installer_not_windows_pe", invalid_installer["failures"])
            self.assertFalse(invalid_installer["artifacts"]["installer"]["pe_signature_valid"])
            installer.write_bytes(b"MZ" + b"\x00" * 128)
            dos_only_installer = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(dos_only_installer["passed"])
            self.assertIn("installer_not_windows_pe", dos_only_installer["failures"])
            self.assertTrue(dos_only_installer["artifacts"]["installer"]["pe_dos_signature_valid"])
            self.assertFalse(dos_only_installer["artifacts"]["installer"]["pe_header_signature_valid"])
            installer.write_bytes(minimal_windows_pe_bytes(b"reachops installer"))
            manifest = build_manifest(installer, version="0.4.0", build="mvp-001", channel="mvp")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            pending_summary = json.loads(json.dumps(summary))
            pending_summary["status"] = "ready_for_external_validation"
            pending_summary["delivery_audit"]["resolved_external_validation"] = 0
            pending_summary["delivery_audit"]["effective_pending_external_validation"] = 3
            pending_summary["live_submit"] = {"status": "skipped"}
            pending_summary["goal_status"] = {
                "status": "ready_for_external_validation",
                "summary": {"stages_passed": 3, "stages_pending_external_validation": 2, "stages_failed": 0},
                "pending_external_validation": ["授权允许时能真实执行", "真实 TikTok 平台提交", "客户端交付验收门禁不会把环境阻断当通过"],
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
            self.assertFalse(pending["final_delivery_ready"])
            self.assertIn(
                "allow_external_pending is an interim validation mode; final delivery requires pending_external_validation=[].",
                pending["not_final_delivery_reasons"],
            )
            self.assertIn(
                "external validation pending: client_delivery_acceptance_gate",
                pending["not_final_delivery_reasons"],
            )
            self.assertIn("client_delivery_acceptance_gate", pending["pending_external_validation"])
            self.assertIn(
                "Rerun client delivery acceptance until acceptance_ready=true and readiness=pass.",
                pending["pending_external_actions"],
            )

            missing_live_input_reports = json.loads(json.dumps(pending_summary))
            missing_live_input_reports["live_readiness"] = {"status": "blocked"}
            missing_live_input_reports["live_preflight"] = {"status": "blocked"}
            acceptance_summary.write_text(json.dumps(missing_live_input_reports), encoding="utf-8")
            missing_reports = check_reachops_delivery_package(
                root=root,
                acceptance_summary_path=acceptance_summary,
                allow_external_pending=True,
            )
            self.assertFalse(missing_reports["passed"])
            self.assertIn("live_readiness_json_path_missing", missing_reports["failures"])
            self.assertIn("live_preflight_json_path_missing", missing_reports["failures"])

            missing_cleanliness_report = json.loads(json.dumps(summary))
            missing_cleanliness_report["repository_cleanliness"] = {"status": "skipped"}
            acceptance_summary.write_text(json.dumps(missing_cleanliness_report), encoding="utf-8")
            missing_cleanliness = check_reachops_delivery_package(root=root, acceptance_summary_path=acceptance_summary)
            self.assertFalse(missing_cleanliness["passed"])
            self.assertIn("repository_cleanliness_json_path_missing", missing_cleanliness["failures"])

    def test_reachops_delivery_package_check_reports_missing_default_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = check_reachops_delivery_package(root=Path(tmp), allow_external_pending=True)

            self.assertFalse(result["passed"])
            self.assertEqual(result["status"], "failed")
            self.assertIn("acceptance_summary_missing", result["failures"])
            self.assertIn("manifest_missing", result["failures"])
            self.assertEqual(result["failures"].count("manifest_missing"), 1)
            self.assertIn("exe", result["missing_artifacts"])
            self.assertIn("installer", result["missing_artifacts"])
            self.assertIn("manifest", result["missing_artifacts"])
            self.assertIn("acceptance_summary", result["missing_artifacts"])
            self.assertTrue(result["artifacts"]["acceptance_summary"]["path"].endswith("reports/reachops_acceptance/acceptance_summary.json"))
            self.assertIn("missing required final artifact: acceptance_summary", result["not_final_delivery_reasons"])
            self.assertIn(
                "acceptance_summary is not passed; rerun acceptance until verification failures and pending items are empty.",
                result["not_final_delivery_reasons"],
            )
            self.assertIn("update manifest is missing; generate reachops-update-manifest.json during the Windows build.", result["not_final_delivery_reasons"])
            remediation = result["remediation_plan"]
            self.assertIn("Windows 最终交付包未闭环", remediation["summary"])
            self.assertIn("exe", remediation["artifact_actions"])
            self.assertIn("installer", remediation["artifact_actions"])
            self.assertIn("manifest", remediation["artifact_actions"])
            self.assertIn("acceptance_summary", remediation["artifact_actions"])
            self.assertTrue(remediation["artifact_actions"]["exe"]["expected_path"].endswith("dist/ReachOps/ReachOps.exe"))
            self.assertTrue(remediation["artifact_actions"]["acceptance_summary"]["expected_path"].endswith("reports/reachops_acceptance/acceptance_summary.json"))
            self.assertIn("tools\\build_reachops_windows.ps1", "\n".join(remediation["commands"]))

    def test_reachops_release_evidence_records_checksums_and_rollback_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "dist" / "ReachOps" / "ReachOps.exe"
            installer = root / "dist" / "installer" / "ReachOps-Setup-0.4.0.exe"
            manifest_path = root / "dist" / "installer" / "reachops-update-manifest.json"
            report_dir = root / "reports" / "reachops_acceptance" / "20260624_120000"
            output_dir = root / "reports" / "reachops_release" / "0.4.0-test"
            exe.parent.mkdir(parents=True, exist_ok=True)
            installer.parent.mkdir(parents=True, exist_ok=True)
            report_dir.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(minimal_windows_pe_bytes(b"release evidence exe"))
            installer.write_bytes(minimal_windows_pe_bytes(b"release evidence installer"))
            manifest_path.write_text(
                json.dumps(build_manifest(installer, version="0.4.0", build="mvp-001", channel="mvp")),
                encoding="utf-8",
            )
            (root / "requirements.lock").write_text(
                "\n".join(
                    [
                        "requests==2.33.0",
                        "Pillow==10.4.0",
                        "selenium==4.41.0",
                        "ixbrowser-local-api==1.2.3",
                        "pyinstaller==6.21.0",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text("-r requirements.lock\n", encoding="utf-8")
            (root / "ReachOps" / "packaging").mkdir(parents=True, exist_ok=True)
            (root / "ReachOps" / "packaging" / "requirements-reachops.txt").write_text("-r ../../requirements.lock\n", encoding="utf-8")
            (root / "ReachOps" / "packaging" / "dependency-license-inventory.json").write_text(
                json.dumps(
                    {
                        "schema_version": "reachops.dependency_license_inventory.v1",
                        "lock_file": "requirements.lock",
                        "dependencies": [
                            {"name": "requests", "version": "2.33.0", "license": "Apache-2.0", "purpose": "HTTP", "runtime_scope": ["ci"]},
                            {"name": "Pillow", "version": "10.4.0", "license": "HPND", "purpose": "Images", "runtime_scope": ["ci"]},
                            {"name": "selenium", "version": "4.41.0", "license": "Apache-2.0", "purpose": "Browser", "runtime_scope": ["ci"]},
                            {"name": "ixbrowser-local-api", "version": "1.2.3", "license": "MIT", "purpose": "Browser API", "runtime_scope": ["ci"]},
                            {"name": "pyinstaller", "version": "6.21.0", "license": "GPL-2.0-or-later with bootloader exception", "purpose": "Build", "runtime_scope": ["windows_build"]},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            acceptance_summary = report_dir / "acceptance_summary.json"
            report_sections = [
                "delivery_audit",
                "operator_pressure",
                "installer_smoke",
                "ui_startup",
                "activation_status",
                "live_acceptance_status",
                "authorization_handoff",
                "live_validation",
                "repository_cleanliness",
                "windows_package_preflight",
                "client_delivery",
                "live_readiness",
                "live_preflight",
                "goal_status",
                "live_submit",
            ]
            summary_sections = {}
            for section in report_sections:
                report_path = report_dir / f"{section}.json"
                report_path.write_text(json.dumps({"status": "passed", "section": section}), encoding="utf-8")
                summary_sections[section] = {"status": "passed", "json_path": str(report_path)}
            (report_dir / "repository_cleanliness_payload.json").write_text(
                json.dumps({"status": "passed"}),
                encoding="utf-8",
            )
            (report_dir / "windows_package_preflight.json").write_text(
                json.dumps({"status": "ready_for_windows_build", "ready_for_windows_build": True}),
                encoding="utf-8",
            )
            client_delivery_path = report_dir / "client_delivery.json"
            write_final_client_delivery_payload(client_delivery_path)
            handoff_path = report_dir / "authorization_handoff_payload.json"
            handoff_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            readiness_md = report_dir / "latest_live_acceptance_readiness.md"
            readiness_json = report_dir / "latest_live_acceptance_readiness.json"
            handoff_bundle = report_dir / "latest_reachops_authorization_handoff.zip"
            readiness_md.write_text("# ReachOps readiness\n", encoding="utf-8")
            readiness_json.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            handoff_bundle.write_bytes(b"handoff bundle")
            summary_sections["repository_cleanliness"] = {
                "status": "passed",
                "json_path": str(report_dir / "repository_cleanliness_payload.json"),
            }
            summary_sections["windows_package_preflight"] = {
                "status": "ready_for_windows_build",
                "ready_for_windows_build": True,
                "json_path": str(report_dir / "windows_package_preflight.json"),
            }
            summary_sections["client_delivery"] = final_client_delivery_payload(str(client_delivery_path))
            summary_sections["client_delivery"]["json_path"] = str(client_delivery_path)
            summary_sections["authorization_handoff"] = {
                "status": "passed",
                "json_path": str(handoff_path),
                "bundle_path": str(handoff_bundle),
                "readiness_report_path": str(readiness_md),
                "readiness_json_path": str(readiness_json),
            }
            issue_closure_payload = {
                **final_issue_closure_payload(),
                "json_path": str(report_dir / "issue_closure_payload.json"),
            }
            final_gate_payload = final_acceptance_gate_payload()
            final_gate_payload["json_path"] = str(report_dir / "final_acceptance_gate.json")
            (report_dir / "issue_closure_payload.json").write_text(json.dumps(issue_closure_payload), encoding="utf-8")
            (report_dir / "final_acceptance_gate.json").write_text(json.dumps(final_gate_payload), encoding="utf-8")
            acceptance_summary.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        **summary_sections,
                        "issue_closure": issue_closure_payload,
                        "final_acceptance_gate": final_gate_payload,
                    }
                ),
                encoding="utf-8",
            )

            evidence = build_reachops_release_evidence(
                root=root,
                version="0.4.0",
                build="mvp-001",
                channel="mvp",
                acceptance_summary=acceptance_summary,
                manifest=manifest_path,
                output_dir=output_dir,
            )

            self.assertEqual(evidence["schema_version"], "reachops.release_evidence.v1")
            self.assertTrue(evidence["dependency_baseline"]["passed"])
            self.assertFalse(evidence["final_delivery_ready"])
            self.assertFalse(evidence["package_check"]["passed"])
            self.assertIn("release_evidence_created_without_strict_final_delivery_package_pass", evidence["not_final_delivery_reasons"])
            self.assertEqual(evidence["artifacts"]["installer"]["sha256"], hashlib.sha256(installer.read_bytes()).hexdigest())
            self.assertEqual(evidence["artifacts"]["manifest"]["sha256"], hashlib.sha256(manifest_path.read_bytes()).hexdigest())
            self.assertEqual(
                evidence["artifacts"]["issue_closure"]["sha256"],
                hashlib.sha256((report_dir / "issue_closure_payload.json").read_bytes()).hexdigest(),
            )
            self.assertEqual(
                evidence["artifacts"]["final_acceptance_gate"]["sha256"],
                hashlib.sha256((report_dir / "final_acceptance_gate.json").read_bytes()).hexdigest(),
            )
            self.assertEqual(
                evidence["artifacts"]["authorization_handoff"]["sha256"],
                hashlib.sha256(handoff_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                evidence["artifacts"]["authorization_handoff_readiness_report"]["sha256"],
                hashlib.sha256(readiness_md.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                evidence["artifacts"]["authorization_handoff_readiness_json"]["sha256"],
                hashlib.sha256(readiness_json.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                evidence["artifacts"]["authorization_handoff_bundle"]["sha256"],
                hashlib.sha256(handoff_bundle.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                evidence["artifacts"]["client_delivery"]["sha256"],
                hashlib.sha256(client_delivery_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(evidence["acceptance"]["summary"]["authorization_handoff"]["status"], "passed")
            self.assertEqual(evidence["acceptance"]["summary"]["client_delivery"]["readiness"], "pass")
            self.assertEqual(evidence["acceptance"]["summary"]["issue_closure"]["schema_version"], "reachops.issue_closure_audit.v1")
            self.assertEqual(evidence["acceptance"]["summary"]["issue_closure"]["summary"]["acceptance_criteria_total"], 53)
            self.assertIn("authorization_handoff", evidence["package_report_files"])
            self.assertIn("client_delivery", evidence["package_report_files"])
            self.assertEqual(evidence["missing_package_report_files"], [])
            self.assertTrue(evidence["rollback"]["final_acceptance_gate"]["exists"])
            self.assertEqual(evidence["rollback"]["final_acceptance_gate"]["status"], "passed")
            self.assertTrue(evidence["rollback"]["final_acceptance_gate"]["final_delivery_ready"])
            self.assertEqual(evidence["rollback"]["final_acceptance_gate"]["failed_checks"], [])
            self.assertIn("python tools\\reachops_issue_closure_audit.py --json", evidence["rollback"]["verification_commands"])
            self.assertTrue(Path(evidence["evidence_path"]).exists())
            rollback_note = Path(evidence["rollback_note_path"]).read_text(encoding="utf-8")
            self.assertIn("ReachOps Rollback Note 0.4.0", rollback_note)
            self.assertIn("Rollback Policy", rollback_note)
            self.assertIn("previous verified ReachOps installer", rollback_note)
            self.assertIn("Missing package reports: none", rollback_note)
            self.assertIn("Authorization handoff evidence", rollback_note)
            self.assertIn("Authorization handoff readiness report", rollback_note)
            self.assertIn("Client delivery evidence", rollback_note)
            self.assertIn("issue_closure", rollback_note)
            self.assertIn("Final acceptance gate evidence", rollback_note)
            self.assertIn("Final acceptance gate status: passed", rollback_note)
            self.assertIn("Final acceptance gate ready: true", rollback_note)
            self.assertIn("Final acceptance gate failed checks: none", rollback_note)

            (report_dir / "live_submit.json").unlink()
            missing_report_evidence = build_reachops_release_evidence(
                root=root,
                version="0.4.0",
                build="mvp-001",
                channel="mvp",
                acceptance_summary=acceptance_summary,
                manifest=manifest_path,
                output_dir=root / "reports" / "reachops_release" / "0.4.0-missing-report",
            )
            self.assertIn("live_submit", missing_report_evidence["missing_package_report_files"])
            missing_report_note = Path(missing_report_evidence["rollback_note_path"]).read_text(encoding="utf-8")
            self.assertIn("Missing package reports: live_submit", missing_report_note)

    def test_reachops_data_governance_verifies_backup_restore_and_redaction_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime" / "data" / "growth_intelligence" / "growth_intelligence.db"
            output_dir = root / "governance"
            report = build_reachops_data_governance_report(
                root=root,
                db_path=db_path,
                output_dir=output_dir,
                create_missing_db=True,
                verify_backup=True,
                verify_privacy_ops=True,
            )

            self.assertEqual(report["schema_version"], "reachops.data_governance.v1")
            self.assertTrue(report["passed"])
            self.assertEqual(report["backup_restore"]["status"], "passed")
            self.assertTrue(Path(report["backup_restore"]["backup_path"]).exists())
            self.assertTrue(Path(report["backup_restore"]["restored_path"]).exists())
            self.assertTrue(report["backup_restore"]["rpo_met"])
            self.assertTrue(report["backup_restore"]["rto_met"])
            self.assertEqual(report["backup_restore"]["recovery_objectives"]["schema_version"], "reachops.recovery_objectives.v1")
            self.assertEqual(report["backup_restore"]["corruption_drill"]["status"], "passed")
            self.assertEqual(report["backup_restore"]["corruption_drill"]["corrupt_integrity_check"], "error")
            self.assertEqual(report["backup_restore"]["corruption_drill"]["restored_integrity_check"], "ok")
            self.assertEqual(report["database"]["schema"]["integrity_check"], "ok")
            self.assertEqual(report["database"]["schema"]["schema_version"], "reachops.sqlite_schema_baseline.v1")
            self.assertGreater(report["database"]["schema"]["table_count"], 20)
            self.assertTrue(report["database"]["migration_policy"]["final_delivery_ready"])
            self.assertEqual(report["database"]["migration_policy"]["current_mode"], "versioned_forward_migrations_with_documented_rollback")
            self.assertIn("20260714_0001_data_privacy_audit", report["database"]["migration_policy"]["applied_versions"])
            self.assertEqual(report["database"]["migrations"]["status"], "passed")
            self.assertEqual(report["database"]["migrations"]["failures"], [])
            self.assertIn("data_privacy_audit", report["database"]["schema"]["tables"])
            self.assertIn("raw_interaction", report["retention_classes"])
            self.assertIn("activation_secret", report["retention_classes"])
            pii_fields = {f"{row['table']}.{row['field']}" for row in report["data_catalog"] if row["classification"] == "pii"}
            self.assertIn("candidate_users.username", pii_fields)
            self.assertIn("action_queue.target_url", pii_fields)
            support = report["support_bundle"]
            self.assertTrue(support["default_redacted"])
            self.assertTrue(support["manifest_required"])
            self.assertEqual(support["manifest_schema_version"], "reachops.support_bundle_manifest.v1")
            self.assertIn("config/reachops_activation_status.json", support["exclude_patterns"])
            self.assertIn("data/growth_intelligence/*.db", support["exclude_patterns"])
            self.assertIn("reports/**/*.png", support["exclude_patterns"])
            self.assertIn("candidate_users.comment_text", support["redacted_fields"])
            self.assertIn("outreach_executions.evidence_path", support["excluded_file_fields"])
            self.assertTrue(support["diagnostic_manifest_complete"])
            self.assertIn("reports/support/delivery_package_check.json", support["required_diagnostics"])
            self.assertIn("reports/support/final_acceptance_gate.json", support["required_diagnostics"])
            self.assertIn("reports/support/issue_closure_payload.json", support["required_diagnostics"])
            support_manifest = support["dry_run_manifest"]
            self.assertTrue(support["dry_run_manifest_passed"])
            self.assertEqual(support_manifest["schema_version"], "reachops.support_bundle_manifest.v1")
            self.assertFalse(support_manifest["activation_status_included"])
            self.assertFalse(support_manifest["raw_database_included"])
            self.assertFalse(support_manifest["evidence_image_included"])
            self.assertEqual(support_manifest["forbidden_included"], [])
            included_support_paths = {item["relative_path"] for item in support_manifest["included_files"]}
            excluded_support_paths = {item["relative_path"] for item in support_manifest["excluded_files"]}
            self.assertIn("logs/reachops.log", included_support_paths)
            self.assertIn("reports/support/diagnostics.json", included_support_paths)
            self.assertIn("reports/support/delivery_package_check.json", included_support_paths)
            self.assertIn("reports/support/final_acceptance_gate.json", included_support_paths)
            self.assertIn("reports/support/issue_closure_payload.json", included_support_paths)
            self.assertIn("reports/support/repository_cleanliness_payload.json", included_support_paths)
            self.assertIn("reports/support/windows_package_preflight.json", included_support_paths)
            self.assertIn("config/reachops_activation_status.json", excluded_support_paths)
            self.assertIn("data/growth_intelligence/growth_intelligence.db", excluded_support_paths)
            self.assertIn("reports/acceptance/action_submit_evidence/submit.png", excluded_support_paths)
            self.assertEqual(report["recovery_objectives"]["rpo_minutes"], 15)
            self.assertEqual(report["recovery_objectives"]["rto_minutes"], 30)
            self.assertEqual(report["privacy_operations"]["audit_table"], "data_privacy_audit")
            self.assertEqual(report["privacy_operations"]["schema_version"], "reachops.privacy_operations.v1")
            privacy_audit = report["privacy_operations"]["audit"]
            self.assertTrue(privacy_audit["passed"])
            self.assertEqual(privacy_audit["observed_operations"], ["delete", "export", "legal_hold"])
            self.assertIn("privacy-export-workspace-audit", privacy_audit["inserted_audit_ids"])
            with sqlite3.connect(db_path) as conn:
                audit_count = conn.execute("SELECT COUNT(*) FROM data_privacy_audit").fetchone()[0]
            self.assertGreaterEqual(audit_count, 3)

            corrupt_db = root / "corrupt.db"
            corrupt_db.write_bytes(b"not sqlite")
            corrupt = build_reachops_data_governance_report(root=root, db_path=corrupt_db, output_dir=output_dir)
            self.assertFalse(corrupt["passed"])
            self.assertIn("database_integrity_failed", corrupt["failures"])
            self.assertIn("migration_status_error", corrupt["failures"])

            legacy_db = root / "legacy.db"
            with sqlite3.connect(legacy_db) as conn:
                conn.execute("CREATE TABLE legacy_marker (id TEXT PRIMARY KEY)")
            migrated = build_reachops_data_governance_report(
                root=root,
                db_path=legacy_db,
                output_dir=output_dir,
                create_missing_db=True,
                verify_backup=True,
                verify_privacy_ops=True,
            )
            self.assertTrue(migrated["passed"])
            self.assertIn("legacy_marker", migrated["database"]["schema"]["tables"])
            self.assertIn("schema_migrations", migrated["database"]["schema"]["tables"])
            self.assertIn("data_privacy_audit", migrated["database"]["schema"]["tables"])
            self.assertIn("20260714_0001_data_privacy_audit", migrated["database"]["migration_policy"]["applied_versions"])

    def test_reachops_outcome_metrics_define_waqo_and_exclude_fixture_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "outcomes.db"
            storage = GrowthStorage(str(db_path))
            now = "2026-07-14T00:00:00Z"
            with storage.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO operation_leads
                    (id, candidate_user_id, lead_type, priority, score, reason, lifecycle_stage,
                     source_path, status, batch_id, created_at, updated_at)
                    VALUES
                    ('lead-real', 'candidate-real', 'purchase', 'high', 92, 'asked for price', 'accepted',
                     'https://www.tiktok.com/@creator/video/1', 'accepted', 'batch-real', ?, ?),
                    ('lead-fixture', 'candidate-fixture', 'purchase', 'high', 99, 'fixture lead', 'accepted',
                     'fixture://source', 'accepted', 'batch-fixture', ?, ?),
                    ('lead-rejected', 'candidate-rejected', 'consult', 'normal', 61, 'not a fit', 'rejected',
                     'https://www.tiktok.com/@creator/video/2', 'rejected', 'batch-real', ?, ?)
                    """,
                    (now, now, now, now, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO lead_outcomes
                    (id, lead_id, workspace_id, owner, qualification_decision, qualification_reason,
                     rejection_reason, lifecycle_stage, dedupe_key, source_path, evidence_path, data_scope,
                     active_followup, accepted_at, reply_at, meaningful_conversation_at, meeting_at, quote_at,
                     order_at, revenue_amount, revenue_currency, lost_reason, attribution_confidence,
                     contact_policy, cost_amount, cost_currency, outcome_ingest_source, outcome_ingested_at,
                     created_at, updated_at)
                    VALUES
                    ('out-real', 'lead-real', 'ws-1', 'owner-1', 'accepted', 'human accepted',
                     '', 'accepted', 'buyer@example.test', 'https://www.tiktok.com/@creator/video/1',
                     'reports/evidence/lead-real.json', 'real_customer', 1, ?, ?, ?, ?, ?, ?,
                     1200.0, 'USD', '', 'operator_confirmed', 'authorized_followup', 300.0, 'USD', 'csv', ?, ?, ?),
                    ('out-fixture', 'lead-fixture', 'ws-1', 'owner-1', 'accepted', 'fixture accepted',
                     '', 'accepted', 'fixture-buyer', 'fixture://source',
                     'fixture://evidence', 'fixture', 1, ?, ?, '', '', '', '',
                     0.0, 'USD', '', 'fixture', 'fixture', 0.0, 'USD', 'fixture', ?, ?, ?),
                    ('out-rejected', 'lead-rejected', 'ws-1', 'owner-1', 'rejected', '',
                     'not ICP', 'rejected', 'rejected-buyer', 'https://www.tiktok.com/@creator/video/2',
                     'reports/evidence/lead-rejected.json', 'real_customer', 0, '', '', '', '', '', '',
                     0.0, 'USD', 'not ICP', 'operator_confirmed', 'not_permitted', 0.0, 'USD', 'webhook', ?, ?, ?)
                    """,
                    (now, now, now, now, now, now, now, now, now, now, now, now, now, now, now, now, now),
                )

            report = build_reachops_outcome_metrics_report(
                db_path=db_path,
                start_at="2026-07-13T00:00:00Z",
                end_at="2026-07-15T00:00:00Z",
            )

            self.assertEqual(report["schema_version"], "reachops.outcome_metrics.v1")
            self.assertTrue(report["passed"])
            self.assertEqual(report["definition"]["schema_version"], "reachops.waqo_definition.v1")
            self.assertEqual(report["definition"]["abbreviation"], "WAQO")
            self.assertIn("data_scope=real_customer", report["definition"]["included"])
            self.assertIn("dry_run", report["definition"]["excluded"])
            self.assertEqual(report["waqo"]["count"], 1)
            self.assertEqual(report["waqo"]["excluded_fixture_or_dry_run"], 1)
            self.assertEqual(report["funnel"]["accepted_opportunities"], 1)
            self.assertEqual(report["funnel"]["fixture_or_dry_run_excluded"], 1)
            self.assertEqual(report["funnel"]["replies"], 1)
            self.assertEqual(report["funnel"]["meaningful_conversations"], 1)
            self.assertEqual(report["funnel"]["meetings"], 1)
            self.assertEqual(report["funnel"]["quotes"], 1)
            self.assertEqual(report["funnel"]["orders"], 1)
            self.assertEqual(report["funnel"]["revenue_amount"], 1200.0)
            self.assertEqual(report["elapsed_time"]["reply"]["average_hours_from_acceptance"], 0.0)
            self.assertEqual(report["conversion_rates"]["reply_rate"], 1.0)
            self.assertEqual(report["pilot_report"]["acceptance_rate"], 0.5)
            self.assertEqual(report["pilot_report"]["cost_per_accepted_opportunity"], 300.0)
            self.assertTrue(report["pilot_report"]["dedupe_enforced_by_unique_key"])
            self.assertEqual(report["quality"]["missing_rejection_reason"], 0)
            self.assertEqual(report["quality"]["accepted_missing_contact_policy"], 0)

            with storage.connect() as conn:
                conn.execute("UPDATE lead_outcomes SET rejection_reason='' WHERE id='out-rejected'")
            rejected_without_reason = build_reachops_outcome_metrics_report(
                db_path=db_path,
                start_at="2026-07-13T00:00:00Z",
                end_at="2026-07-15T00:00:00Z",
            )
            self.assertFalse(rejected_without_reason["passed"])
            self.assertIn("rejected_leads_missing_reason", rejected_without_reason["failures"])

    def test_reachops_outcome_metrics_ingest_csv_and_webhook_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "outcomes.db"
            csv_path = root / "outcomes.csv"
            now = "2026-07-14T00:00:00Z"
            csv_path.write_text(
                "\n".join(
                    [
                        "id,lead_id,workspace_id,owner,qualification_decision,qualification_reason,rejection_reason,lifecycle_stage,dedupe_key,source_path,evidence_path,data_scope,active_followup,accepted_at,reply_at,meaningful_conversation_at,meeting_at,quote_at,order_at,revenue_amount,revenue_currency,lost_reason,attribution_confidence,contact_policy,cost_amount,cost_currency,created_at",
                        f"out-csv,lead-csv,ws-1,owner-1,accepted,human accepted,,accepted,csv-buyer,https://source.example/1,reports/evidence/csv.json,real_customer,1,{now},{now},{now},{now},,{now},900,USD,,operator_confirmed,authorized_followup,90,USD,{now}",
                    ]
                ),
                encoding="utf-8",
            )

            csv_result = import_reachops_outcomes_csv(db_path=db_path, csv_path=csv_path)
            self.assertTrue(csv_result["passed"])
            self.assertEqual(csv_result["schema_version"], "reachops.outcome_ingestion.v1")
            self.assertEqual(csv_result["imported"], 1)

            webhook_result = import_reachops_outcomes_webhook_payload(
                db_path=db_path,
                payload={
                    "id": "out-webhook",
                    "lead_id": "lead-webhook",
                    "workspace_id": "ws-1",
                    "owner": "owner-2",
                    "qualification_decision": "rejected",
                    "rejection_reason": "not in pilot segment",
                    "dedupe_key": "webhook-buyer",
                    "source_path": "https://source.example/2",
                    "evidence_path": "reports/evidence/webhook.json",
                    "data_scope": "real_customer",
                    "contact_policy": "do_not_contact",
                    "created_at": now,
                },
            )
            self.assertTrue(webhook_result["passed"])
            self.assertEqual(webhook_result["imported"], 1)

            report = build_reachops_outcome_metrics_report(
                db_path=db_path,
                start_at="2026-07-13T00:00:00Z",
                end_at="2026-07-15T00:00:00Z",
            )
            self.assertTrue(report["passed"])
            self.assertEqual(report["waqo"]["count"], 1)
            self.assertEqual(report["funnel"]["orders"], 1)
            self.assertEqual(report["pilot_report"]["precision"], 0.5)
            self.assertEqual(report["pilot_report"]["cost_per_accepted_opportunity"], 90.0)

    def test_reachops_security_supply_chain_audit_covers_entitlement_and_update_manifest(self):
        report = build_reachops_security_supply_chain_report()

        self.assertEqual(report["schema_version"], "reachops.security_supply_chain_audit.v1")
        self.assertTrue(report["passed"])
        entitlement = report["entitlement"]
        self.assertEqual(entitlement["schema_version"], "reachops.entitlement_security_matrix.v1")
        self.assertTrue(entitlement["cases"]["valid_signed"]["allowed"])
        self.assertTrue(entitlement["cases"]["rotated_new_key"]["allowed"])
        self.assertFalse(entitlement["cases"]["retired_old_key"]["allowed"])
        self.assertEqual(entitlement["cases"]["retired_old_key"]["signature_reason"], "signature_key_unknown")
        self.assertEqual(entitlement["cases"]["replay_detected"]["error_code"], "LIVE_SUBMIT_ENTITLEMENT_REPLAYED")
        self.assertEqual(entitlement["cases"]["revoked"]["error_code"], "LIVE_SUBMIT_ENTITLEMENT_REVOKED")
        self.assertEqual(entitlement["revocation_sla_hours"], 24)
        update = report["update_supply_chain"]
        self.assertEqual(update["schema_version"], "reachops.update_supply_chain_matrix.v1")
        self.assertTrue(update["signature_valid"])
        self.assertTrue(update["installer_verified"])
        self.assertEqual(update["evidence_contract_schema"], "reachops.update_manifest_evidence.v1")
        self.assertTrue(update["release_evidence_required"])
        self.assertTrue(update["acceptance_summary_required"])
        self.assertTrue(update["final_package_check_required"])
        self.assertTrue(update["final_acceptance_gate_required"])
        self.assertTrue(update["issue_closure_required"])
        self.assertIn("authorization_handoff", update["required_report_files"])
        self.assertIn("client_delivery", update["required_report_files"])
        self.assertTrue(update["missing_evidence_contract_rejected"])
        self.assertTrue(update["incomplete_evidence_contract_rejected"])
        self.assertTrue(update["tampered_manifest_rejected"])
        self.assertTrue(update["bad_installer_hash_or_size_rejected"])
        self.assertTrue(update["http_manifest_rejected"])
        self.assertTrue(update["https_signed_manifest_loaded"])
        self.assertTrue(update["downgrade_without_rollback_blocked"])
        self.assertTrue(update["explicit_rollback_available"])
        self.assertIn("manifest_signature", update["verified_fields"])
        self.assertIn("evidence.required_report_files", update["verified_fields"])

    def test_reachops_start_contract_audit_covers_rejections_and_auditability(self):
        report = build_reachops_start_contract_report()

        self.assertEqual(report["schema_version"], "reachops.start_contract_audit.v1")
        self.assertEqual(report["contract_version"], "reachops.api_start_contract.v1")
        self.assertTrue(report["passed"])
        self.assertEqual(report["failed_cases"], [])
        cases = {row["name"]: row for row in report["rejection_cases"]}
        for name in [
            "missing_target",
            "untrusted_origin",
            "group_list_unavailable",
            "group_not_found",
            "group_counts_incomplete",
            "account_repair_required",
            "live_comment_confirmation_required",
            "live_submit_not_authorized",
            "already_running",
        ]:
            self.assertTrue(cases[name]["passed"], name)
            self.assertTrue(cases[name]["no_browser_started"], name)
            self.assertTrue(cases[name]["no_submit"], name)
            self.assertTrue(cases[name]["next_action"], name)
        self.assertTrue(report["success_contract"]["execution_plan_persisted"])
        self.assertTrue(report["success_contract"]["run_session_persisted"])
        self.assertTrue(report["auditability"]["blocked_group_start_writes_execution_plan"])
        self.assertTrue(report["auditability"]["blocked_group_start_writes_run_session"])
        self.assertTrue(report["auditability"]["blocked_group_start_writes_page_state_sidecar"])

    def test_reachops_delivery_package_check_rejects_external_summary_and_manifest_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            outside_summary = outside / "acceptance_summary.json"
            outside_manifest = outside / "reachops-update-manifest.json"
            outside_summary.write_text("{}", encoding="utf-8")
            outside_manifest.write_text("{}", encoding="utf-8")

            result = check_reachops_delivery_package(
                root=root,
                acceptance_summary_path=outside_summary,
                manifest_path=outside_manifest,
                allow_external_pending=True,
            )

        self.assertFalse(result["passed"])
        self.assertIn("acceptance_summary_outside_root", result["failures"])
        self.assertIn("manifest_outside_root", result["failures"])
        self.assertEqual(result["artifacts"]["acceptance_summary"]["path"], str(outside_summary))
        self.assertEqual(result["artifacts"]["manifest"]["path"], str(outside_manifest))

    def test_reachops_final_acceptance_gate_requires_client_and_package_final_ready(self):
        gate = build_reachops_final_acceptance_gate(
            goal_status=final_goal_status_payload(
                status="ready_for_external_validation",
                pending_external_validation=["真实 TikTok 平台提交"],
            ),
            client_delivery={
                "status": "blocked_by_environment",
                "readiness": "blocked_by_environment",
                "contract_ok": True,
                "acceptance_ready": False,
                "final_delivery_ready": False,
                "failed_checks": ["acceptance:ready"],
                "blockers": ["ixBrowser local API not ready"],
                "delivery_check_path": "reports/acceptance_remediation/latest_delivery_check.json",
            },
            package_check={
                "status": "failed",
                "passed": False,
                "final_delivery_ready": False,
                "missing_artifacts": ["exe", "installer", "manifest", "acceptance_summary"],
                "failures": ["exe_missing", "installer_missing", "manifest_missing", "acceptance_summary_missing"],
                "artifacts": {"acceptance_summary": {"path": "reports/reachops_acceptance/acceptance_summary.json", "exists": False}},
                "report_files": {"final_acceptance_gate": {"path": "", "exists": False}},
            },
            issue_closure={
                "schema_version": "reachops.issue_closure_audit.v1",
                "status": "passed_with_external_acceptance_pending",
                "passed": True,
                "github_issues": {"closure_requires_external_validation": True},
                "summary": {
                    "issues_total": 7,
                    "local_contracts_passed": 7,
                    "acceptance_criteria_total": 53,
                    "acceptance_criteria_local_passed": 36,
                    "acceptance_criteria_external_pending": 17,
                    "acceptance_criteria_unclassified": 0,
                    "external_pending_count": 36,
                },
                "external_acceptance_pending": ["issue_3_100_real_no_submit_runs_three_industries"],
            },
            delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 41, "pending_external_validation": 3}},
            operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
        )

        self.assertEqual(gate["status"], "not_ready")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("goal_status:passed", gate["failed_checks"])
        self.assertIn("client_delivery:final_ready", gate["failed_checks"])
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        self.assertIn("commercial_issue_closure:closed", gate["failed_checks"])
        checks_by_name = {row["name"]: row for row in gate["checks"]}
        self.assertNotIn("current_stage_gate:local_ready_or_external_pending", gate["failed_checks"])
        self.assertTrue(checks_by_name["current_stage_gate:local_ready_or_external_pending"]["ok"])
        self.assertEqual(
            checks_by_name["current_stage_gate:local_ready_or_external_pending"]["status"],
            "ready_for_external_validation",
        )
        self.assertEqual(
            checks_by_name["client_delivery:final_ready"]["evidence"]["delivery_check_path"],
            "reports/acceptance_remediation/latest_delivery_check.json",
        )
        self.assertIn("acceptance_summary", checks_by_name["delivery_package:passed"]["evidence"]["artifacts"])
        self.assertIn("final_acceptance_gate", checks_by_name["delivery_package:passed"]["evidence"]["report_files"])
        self.assertFalse(checks_by_name["delivery_package:passed"]["evidence"]["final_delivery_ready"])
        blockers = {row["scope"]: row for row in gate["final_delivery_blockers"]}
        self.assertIn("external_authorized_execution", blockers)
        self.assertIn("client_delivery_gate", blockers)
        self.assertIn("windows_final_artifacts", blockers)
        self.assertIn("commercial_issue_closure", blockers)
        self.assertIn("acceptance_summary", blockers["windows_final_artifacts"]["missing_artifacts"])
        evidence_plan = gate["final_delivery_evidence_plan"]
        self.assertEqual(evidence_plan["schema_version"], "reachops.final_delivery_evidence_plan.v1")
        self.assertFalse(evidence_plan["ready"])
        self.assertIn("external_authorized_execution", evidence_plan["pending_scopes"])
        self.assertIn("client_delivery_gate", evidence_plan["pending_scopes"])
        self.assertIn("windows_final_artifacts", evidence_plan["pending_scopes"])
        self.assertIn("commercial_issue_closure", evidence_plan["pending_scopes"])
        plan_items = {row["scope"]: row for row in evidence_plan["items"]}
        self.assertIn("goal_status.pending_external_validation=[]", plan_items["external_authorized_execution"]["proof_fields"])
        self.assertIn("client_delivery.final_delivery_ready=true", plan_items["client_delivery_gate"]["proof_fields"])
        self.assertIn("delivery_package.final_delivery_ready=true", plan_items["windows_final_artifacts"]["proof_fields"])
        self.assertIn("dist\\ReachOps\\ReachOps.exe", plan_items["windows_final_artifacts"]["required_artifacts"])
        self.assertIn("issue_closure.summary.acceptance_criteria_external_pending=0", plan_items["commercial_issue_closure"]["proof_fields"])
        self.assertTrue(any("Windows 实机生成" in item for item in gate["next_actions"]))

    def test_reachops_final_acceptance_gate_passes_only_when_all_final_evidence_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=final_package_check_payload(),
                issue_closure=final_issue_closure_payload(),
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "passed")
        self.assertTrue(gate["final_delivery_ready"])

    def test_reachops_final_acceptance_gate_requires_current_stage_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            goal_status = final_goal_status_payload()
            goal_status["current_stage_gate"]["local_passed"] = False
            goal_status["current_stage_gate"]["local_checks"]["client_delivery_reports_real_pilot_boundary"] = False
            gate = build_reachops_final_acceptance_gate(
                goal_status=goal_status,
                client_delivery=client_payload,
                package_check=final_package_check_payload(),
                issue_closure=final_issue_closure_payload(),
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("current_stage_gate:local_ready_or_external_pending", gate["failed_checks"])
        checks_by_name = {row["name"]: row for row in gate["checks"]}
        self.assertFalse(checks_by_name["current_stage_gate:local_ready_or_external_pending"]["evidence"]["local_passed"])
        blockers = {row["scope"]: row for row in gate["final_delivery_blockers"]}
        self.assertIn("current_stage_gate", blockers)
        self.assertIn("current_stage_gate", gate["final_delivery_evidence_plan"]["pending_scopes"])

    def test_reachops_final_acceptance_gate_rejects_client_without_persisted_delivery_check(self):
        gate = build_reachops_final_acceptance_gate(
            goal_status=final_goal_status_payload(),
            client_delivery=final_client_delivery_payload("/tmp/reachops-missing-latest-delivery-check.json"),
            package_check=final_package_check_payload(),
            delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
            operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
        )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("client_delivery:final_ready", gate["failed_checks"])
        client_evidence = {row["name"]: row for row in gate["checks"]}["client_delivery:final_ready"]["evidence"]
        self.assertFalse(client_evidence["evidence_ready"])

    def test_reachops_final_acceptance_gate_rejects_client_with_invalid_delivery_check_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = final_client_delivery_payload(str(client_path))
            blocked_payload = dict(client_payload)
            blocked_payload["status"] = "blocked_by_environment"
            blocked_payload["readiness"] = "blocked_by_environment"
            blocked_payload["acceptance_ready"] = False
            blocked_payload["final_delivery_ready"] = False
            blocked_payload["failed_checks"] = ["acceptance:ready"]
            client_path.write_text(json.dumps(blocked_payload), encoding="utf-8")
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=final_package_check_payload(),
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertIn("client_delivery:final_ready", gate["failed_checks"])
        client_evidence = {row["name"]: row for row in gate["checks"]}["client_delivery:final_ready"]["evidence"]
        self.assertFalse(client_evidence["evidence_ready"])

    def test_reachops_final_acceptance_gate_rejects_package_with_weak_inner_evidence(self):
        package_check = final_package_check_payload()
        package_check["acceptance_verification"] = {"passed": False, "failures": ["final_acceptance_gate_missing"], "pending": []}
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_evidence = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]["evidence"]
        self.assertEqual(package_evidence["acceptance_verification"]["failures"], ["final_acceptance_gate_missing"])

    def test_reachops_final_acceptance_gate_rejects_package_without_final_gate_report_summary(self):
        package_check = final_package_check_payload()
        package_check.pop("final_gate_report", None)
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_evidence = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]["evidence"]
        self.assertEqual(package_evidence["final_gate_report"], {})

    def test_reachops_final_acceptance_gate_rejects_package_with_failed_final_gate_report_summary(self):
        package_check = final_package_check_payload()
        package_check["final_gate_report"]["failed_required_checks"] = ["delivery_package:passed"]
        package_check["final_gate_report"]["checks_by_name"]["delivery_package:passed"]["ok"] = False
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_evidence = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]["evidence"]
        self.assertEqual(package_evidence["final_gate_report"]["failed_required_checks"], ["delivery_package:passed"])

    def test_reachops_final_acceptance_gate_accepts_package_convergence_pass(self):
        package_check = final_package_check_payload()
        package_check["allow_final_gate_convergence"] = True
        package_check["final_gate_report"]["status"] = "not_ready"
        package_check["final_gate_report"]["final_delivery_ready"] = False
        package_check["final_gate_report"]["failed_checks"] = ["delivery_package:passed"]
        package_check["final_gate_report"]["failed_required_checks"] = ["delivery_package:passed"]
        package_check["final_gate_report"]["convergence_only"] = True
        package_check["final_gate_report"]["checks_by_name"]["delivery_package:passed"]["ok"] = False
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )
        self.assertEqual(gate["status"], "passed")
        self.assertTrue(gate["final_delivery_ready"])
        self.assertEqual(gate["failed_checks"], [])

    def test_reachops_final_acceptance_gate_rejects_empty_package_artifact_evidence(self):
        package_check = final_package_check_payload()
        package_check["artifacts"]["installer"]["size"] = 0
        package_check["report_files"]["final_acceptance_gate"]["size"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_evidence = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]["evidence"]
        self.assertEqual(package_evidence["artifacts"]["installer"]["size"], 0)
        self.assertEqual(package_evidence["report_files"]["final_acceptance_gate"]["size"], 0)

    def test_reachops_final_acceptance_gate_rejects_package_without_pe_artifact_evidence(self):
        package_check = final_package_check_payload()
        package_check["artifacts"]["exe"]["pe_signature_valid"] = False
        package_check["artifacts"]["installer"].pop("pe_signature_valid")
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_evidence = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]["evidence"]
        self.assertFalse(package_evidence["artifacts"]["exe"]["pe_signature_valid"])
        self.assertNotIn("pe_signature_valid", package_evidence["artifacts"]["installer"])

    def test_reachops_final_acceptance_gate_rejects_package_manifest_mismatch_evidence(self):
        package_check = final_package_check_payload()
        package_check["artifacts"]["manifest"]["actual_sha256"] = "b" * 64
        package_check["artifacts"]["manifest"]["actual_size"] = 11
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_evidence = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]["evidence"]
        self.assertNotEqual(
            package_evidence["artifacts"]["manifest"]["actual_sha256"],
            package_evidence["artifacts"]["manifest"]["expected_sha256"],
        )

    def test_reachops_final_acceptance_gate_rejects_package_missing_required_report_file(self):
        package_check = final_package_check_payload()
        package_check["report_files"].pop("authorization_handoff")
        package_check["report_files"]["live_preflight"]["size"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "latest_delivery_check.json"
            client_payload = write_final_client_delivery_payload(client_path)
            gate = build_reachops_final_acceptance_gate(
                goal_status=final_goal_status_payload(),
                client_delivery=client_payload,
                package_check=package_check,
                delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
                operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
            )

        self.assertEqual(gate["status"], "failed")
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_evidence = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]["evidence"]
        self.assertNotIn("authorization_handoff", package_evidence["report_files"])
        self.assertEqual(package_evidence["report_files"]["live_preflight"]["size"], 0)

    def test_reachops_final_acceptance_gate_rejects_bootstrap_package_check(self):
        gate = build_reachops_final_acceptance_gate(
            goal_status=final_goal_status_payload(),
            client_delivery={
                "status": "passed",
                "readiness": "pass",
                "contract_ok": True,
                "acceptance_ready": True,
                "final_delivery_ready": True,
                "failed_checks": [],
            },
            package_check={
                "status": "passed",
                "passed": True,
                "final_delivery_ready": False,
                "bootstrap_only": True,
                "not_final_delivery_reasons": ["allow_missing_final_gate is bootstrap-only"],
                "missing_artifacts": [],
                "failures": [],
                "pending_external_validation": [],
            },
            delivery_audit={"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}},
            operator_pressure={"status": "ok", "summary": {"customer_leads": 108, "outreach_actions": 216}},
        )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("delivery_package:passed", gate["failed_checks"])
        package_check = {row["name"]: row for row in gate["checks"]}["delivery_package:passed"]
        self.assertTrue(package_check["evidence"]["bootstrap_only"])
        self.assertIn("allow_missing_final_gate", package_check["evidence"]["not_final_delivery_reasons"][0])

    def test_reachops_final_acceptance_gate_default_command_includes_audit_and_pressure(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_payload = {"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}}
            pressure_payload = {"status": "ok", "summary": {"customer_leads": 12, "outreach_actions": 24}}
            goal_payload = final_goal_status_payload()
            client_payload = {
                "status": "passed",
                "readiness": "pass",
                "contract_ok": True,
                "acceptance_ready": True,
                "final_delivery_ready": True,
                "failed_checks": [],
                "delivery_check_path": str(Path(tmp) / "latest_delivery_check.json"),
            }
            Path(client_payload["delivery_check_path"]).write_text(json.dumps(client_payload), encoding="utf-8")
            package_payload = final_package_check_payload()

            stdout = io.StringIO()
            with patch("tools.reachops_final_acceptance_gate.run_default_audit", return_value=audit_payload) as audit_mock:
                with patch("tools.reachops_final_acceptance_gate.run_default_pressure", return_value=pressure_payload) as pressure_mock:
                    with patch("tools.reachops_final_acceptance_gate.build_goal_status_report", return_value=goal_payload) as goal_mock:
                        with patch("tools.reachops_final_acceptance_gate.build_delivery_check", return_value=client_payload):
                            with patch("tools.reachops_final_acceptance_gate.check_delivery_package", return_value=package_payload):
                                with patch(
                                    "tools.reachops_final_acceptance_gate.build_issue_closure_report",
                                    return_value=final_issue_closure_payload(),
                                ) as issue_mock:
                                    with redirect_stdout(stdout):
                                        exit_code = reachops_final_acceptance_gate_main(["--root", tmp, "--json"])

            payload = json.loads(stdout.getvalue())
            check_names = [row["name"] for row in payload["checks"]]
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "passed")
            self.assertIn("current_stage_gate:local_ready_or_external_pending", check_names)
            self.assertIn("delivery_audit:no_failed_checks", check_names)
            self.assertIn("operator_pressure:leads_and_actions", check_names)
            self.assertIn("commercial_issue_closure:closed", check_names)
            audit_mock.assert_called_once()
            pressure_mock.assert_called_once()
            goal_mock.assert_called_once_with(audit_payload, client_delivery=client_payload)
            issue_mock.assert_called_once()

    def test_reachops_final_acceptance_gate_default_audit_failure_returns_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with patch("tools.reachops_final_acceptance_gate.run_default_audit", side_effect=RuntimeError("audit failed")):
                with redirect_stdout(stdout):
                    exit_code = reachops_final_acceptance_gate_main(["--root", tmp, "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["final_delivery_ready"])
        self.assertEqual(payload["failed_checks"], ["delivery_audit:no_failed_checks"])
        self.assertEqual(payload["checks"][0]["evidence"]["error_type"], "RuntimeError")

    def test_reachops_final_acceptance_gate_rejects_external_json_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            external_audit = outside / "audit.json"
            external_package = outside / "package.json"
            external_audit.write_text("{}", encoding="utf-8")
            external_package.write_text("{}", encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = reachops_final_acceptance_gate_main(
                    [
                        "--root",
                        str(root),
                        "--audit-json",
                        str(external_audit),
                        "--package-check-json",
                        str(external_package),
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["final_delivery_ready"])
        self.assertEqual(payload["failed_checks"], ["input_paths:inside_root"])
        input_evidence = payload["checks"][0]["evidence"]
        self.assertIn("audit_json_outside_root", input_evidence["failures"])
        self.assertIn("package_check_json_outside_root", input_evidence["failures"])

    def test_reachops_final_acceptance_gate_rejects_package_check_from_different_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()

            audit_json = root / "audit.json"
            pressure_json = root / "pressure.json"
            goal_json = root / "goal.json"
            client_json = root / "client.json"
            delivery_check_json = root / "latest_delivery_check.json"
            package_json = root / "package.json"

            audit_json.write_text(
                json.dumps({"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}}),
                encoding="utf-8",
            )
            pressure_json.write_text(
                json.dumps({"status": "ok", "summary": {"customer_leads": 12, "outreach_actions": 24}}),
                encoding="utf-8",
            )
            goal_json.write_text(
                json.dumps({"status": "passed", "pending_external_validation": [], "summary": {"final_failed": 0}}),
                encoding="utf-8",
            )
            client_payload = write_final_client_delivery_payload(delivery_check_json)
            client_payload["root_dir"] = str(root.resolve())
            delivery_check_json.write_text(json.dumps(client_payload), encoding="utf-8")
            client_json.write_text(json.dumps(client_payload), encoding="utf-8")

            package_payload = final_package_check_payload()
            package_payload["root"] = str(outside)
            package_json.write_text(json.dumps(package_payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = reachops_final_acceptance_gate_main(
                    [
                        "--root",
                        str(root),
                        "--audit-json",
                        str(audit_json),
                        "--pressure-json",
                        str(pressure_json),
                        "--goal-status-json",
                        str(goal_json),
                        "--client-delivery-json",
                        str(client_json),
                        "--package-check-json",
                        str(package_json),
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["final_delivery_ready"])
        self.assertEqual(payload["failed_checks"], ["package_check:root_matches"])
        evidence = payload["checks"][0]["evidence"]
        self.assertEqual(evidence["root"], str(root.resolve()))
        self.assertEqual(evidence["package_check_root"], str(outside))
        self.assertEqual(evidence["package_check_json"], str(package_json.resolve()))

    def test_reachops_final_acceptance_gate_rejects_client_delivery_from_different_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()

            audit_json = root / "audit.json"
            pressure_json = root / "pressure.json"
            goal_json = root / "goal.json"
            client_json = root / "client.json"
            external_delivery_check_json = outside / "latest_delivery_check.json"
            package_json = root / "package.json"

            audit_json.write_text(
                json.dumps({"status": "ok", "summary": {"failed": 0, "passed": 44, "pending_external_validation": 0}}),
                encoding="utf-8",
            )
            pressure_json.write_text(
                json.dumps({"status": "ok", "summary": {"customer_leads": 12, "outreach_actions": 24}}),
                encoding="utf-8",
            )
            goal_json.write_text(
                json.dumps({"status": "passed", "pending_external_validation": [], "summary": {"final_failed": 0}}),
                encoding="utf-8",
            )
            client_payload = final_client_delivery_payload(str(external_delivery_check_json))
            client_payload["root_dir"] = str(outside)
            external_delivery_check_json.write_text(json.dumps(client_payload), encoding="utf-8")
            client_json.write_text(json.dumps(client_payload), encoding="utf-8")
            package_payload = final_package_check_payload()
            package_payload["root"] = str(root.resolve())
            package_json.write_text(json.dumps(package_payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = reachops_final_acceptance_gate_main(
                    [
                        "--root",
                        str(root),
                        "--audit-json",
                        str(audit_json),
                        "--pressure-json",
                        str(pressure_json),
                        "--goal-status-json",
                        str(goal_json),
                        "--client-delivery-json",
                        str(client_json),
                        "--package-check-json",
                        str(package_json),
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["final_delivery_ready"])
        self.assertEqual(payload["failed_checks"], ["client_delivery:root_matches"])
        evidence = payload["checks"][0]["evidence"]
        self.assertEqual(evidence["root"], str(root.resolve()))
        self.assertEqual(evidence["client_root_dir"], str(outside))
        self.assertEqual(evidence["delivery_check_path"], str(external_delivery_check_json))
        self.assertFalse(evidence["delivery_check_inside_root"])

    def test_reachops_final_acceptance_gate_explains_audit_and_pressure_failures(self):
        gate = build_reachops_final_acceptance_gate(
            goal_status={"status": "passed", "pending_external_validation": [], "summary": {"final_failed": 0}},
            client_delivery=reachops_client_delivery_from_acceptance_summary(
                {
                    "status": "passed",
                    "live_acceptance_status": {"status": "passed", "final_delivery_ready": True},
                    "client_delivery": final_client_delivery_payload("client_delivery.json"),
                }
            ),
            package_check=final_package_check_payload(),
            delivery_audit={"status": "ok", "summary": {"failed": 1, "passed": 43, "pending_external_validation": 0}},
            operator_pressure={"status": "failed", "summary": {"customer_leads": 0, "outreach_actions": 0}},
        )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["final_delivery_ready"])
        self.assertIn("delivery_audit:no_failed_checks", gate["failed_checks"])
        self.assertIn("operator_pressure:leads_and_actions", gate["failed_checks"])
        blockers = {row["scope"]: row for row in gate["final_delivery_blockers"]}
        self.assertIn("delivery_audit", blockers)
        self.assertIn("operator_pressure", blockers)
        self.assertTrue(any("reachops_delivery_audit" in item for item in gate["next_actions"]))
        self.assertTrue(any("运营压测" in item for item in gate["next_actions"]))

    def test_reachops_final_gate_can_use_windows_acceptance_summary_for_client_delivery(self):
        blocked = reachops_client_delivery_from_acceptance_summary(
            {
                "status": "ready_for_external_validation",
                "live_acceptance_status": {
                    "status": "blocked",
                    "final_delivery_ready": False,
                    "next_required_actions": ["运行受控真实提交并生成 live submit evidence"],
                },
            }
        )
        self.assertEqual(blocked["status"], "blocked_by_environment")
        self.assertFalse(blocked["final_delivery_ready"])
        self.assertEqual(blocked["failed_checks"], ["client_delivery:missing"])

        missing_client_delivery = reachops_client_delivery_from_acceptance_summary(
            {
                "status": "passed",
                "live_acceptance_status": {
                    "status": "passed",
                    "final_delivery_ready": True,
                    "next_required_actions": [],
                },
            }
        )
        self.assertEqual(missing_client_delivery["status"], "blocked_by_environment")
        self.assertEqual(missing_client_delivery["failed_checks"], ["client_delivery:missing"])

        passed = reachops_client_delivery_from_acceptance_summary(
            {
                "status": "passed",
                "live_acceptance_status": {
                    "status": "passed",
                    "final_delivery_ready": True,
                    "next_required_actions": [],
                },
                "client_delivery": final_client_delivery_payload("client_delivery.json"),
            }
        )
        self.assertEqual(passed["status"], "passed")
        self.assertEqual(passed["readiness"], "pass")
        self.assertTrue(passed["acceptance_ready"])
        self.assertTrue(passed["final_delivery_ready"])
        self.assertEqual(passed["failed_checks"], [])
        self.assertEqual(passed["source"], "acceptance_summary.client_delivery")

    def test_reachops_live_preflight_script_runs_without_submit_using_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Args:
                base_dir = tmp
                profile_ids = "12345,67890"
                group_name = "AUDIT"
                video_url = "https://www.tiktok.com/@creator/video/123"
                profile_url = "https://www.tiktok.com/@buyer_one"
                dm_profile_url = "https://www.tiktok.com/@buyer_one/inbox"
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
            self.assertEqual(result["target_urls"]["follow_review"], "https://www.tiktok.com/@buyer_one")
            self.assertEqual(result["target_urls"]["dm_review"], "https://www.tiktok.com/@buyer_one/inbox")
            self.assertEqual(result["environment_diagnostics"]["status"], "ready")
            comment_evidence = result["preflight_action_statuses"]["comment_reply"][0]["evidence_file_path"]
            self.assertTrue(Path(comment_evidence).is_file())
            sidecar = json.loads(Path(comment_evidence).read_text(encoding="utf-8"))
            self.assertTrue(sidecar["no_submit"])
            self.assertTrue(sidecar["preflight_only"])
            self.assertEqual(sidecar["action_type"], "comment_reply")
            self.assertEqual(sidecar["target_url"], "https://www.tiktok.com/@creator/video/123")
            self.assertEqual(result["evidence_file_details"]["comment_reply"][0]["path"], comment_evidence)
            self.assertTrue(result["summary"].get("report", {}).get("json_path"))

    def test_reachops_live_preflight_reports_missing_inputs_without_browser_or_submit(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Args:
                base_dir = tmp
                profile_ids = ""
                group_name = "AUDIT"
                video_url = ""
                profile_url = ""
                dm_profile_url = ""
                target_username = ""
                workers = 2
                per_profile_limit = 3
                switch_attempts = 2
                per_profile_hour_limit = 20
                per_profile_video_hour_limit = 5
                page_timeout = 1
                element_timeout = 1

            result = run_reachops_live_preflight(Args())

            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["ready"])
            self.assertTrue(result["no_browser_started"])
            self.assertTrue(result["no_submit"])
            self.assertTrue(result["preflight_only"])
            self.assertIn("--profile-ids must include at least one profile id", result["errors"])
            self.assertIn("--video-url is required", result["errors"])
            self.assertIn("--profile-url is required", result["errors"])
            self.assertIn("--dm-profile-url is required", result["errors"])
            self.assertEqual(result["environment_diagnostics"]["blocking_stage"], "input_validation")

    def test_reachops_live_preflight_classifies_ixbrowser_proxy_environment_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Args:
                base_dir = tmp
                profile_ids = "27273,27240"
                group_name = "BR"
                video_url = "https://www.tiktok.com/@creator/video/123"
                profile_url = "https://www.tiktok.com/@target_user"
                dm_profile_url = "https://www.tiktok.com/@target_user"
                target_username = "target_user"
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
                        {
                            "status": "failed",
                            "error_code": "PROFILE_START_FAILED",
                            "error_message": "ixBrowser open_profile failed: code=1003 message=Proxy detection failed:Connection Error: Socks5 Authentication failed; legacy fallback failed: No module named 'modules'",
                        }
                    ]
                ),
            )

            diagnostics = result["environment_diagnostics"]
            failure_count = sum(
                int(row["attempts"])
                for row in diagnostics["profile_failures"]
                if "profile_start_failed" in row["classifications"]
            )
            self.assertEqual(diagnostics["status"], "blocked")
            self.assertEqual(diagnostics["blocking_stage"], "ixbrowser_open_profile")
            self.assertGreaterEqual(failure_count, 1)
            self.assertGreaterEqual(diagnostics["classification_counts"]["profile_start_failed"], 1)
            self.assertEqual(
                diagnostics["classification_counts"]["proxy_detection_failed"],
                diagnostics["classification_counts"]["profile_start_failed"],
            )
            self.assertEqual(
                diagnostics["classification_counts"]["socks5_auth_failed"],
                diagnostics["classification_counts"]["profile_start_failed"],
            )
            self.assertEqual(
                diagnostics["classification_counts"]["legacy_adapter_missing"],
                diagnostics["classification_counts"]["profile_start_failed"],
            )
            self.assertTrue(set(diagnostics["failed_profile_ids"]).issubset({"27273", "27240"}))
            self.assertEqual(
                diagnostics["error_counts"]["PROFILE_START_FAILED"],
                diagnostics["classification_counts"]["profile_start_failed"],
            )
            self.assertIsInstance(diagnostics["account_switches"], list)
            self.assertIn("Fix ixBrowser profile proxy credentials and pass ixBrowser proxy detection.", diagnostics["next_required_actions"])
            self.assertEqual(set(result["missing_preflight_action_types"]), {"comment_reply", "follow_review", "dm_review"})

    def test_reachops_live_preflight_environment_diagnostics_separates_account_switches(self):
        diagnostics = build_reachops_live_preflight_environment_diagnostics(
            [
                {
                    "status": "failed",
                    "profile_id": "27240",
                    "error_code": "PROFILE_START_FAILED",
                    "error_message": "Proxy detection failed: Connection Error: Socks5 Authentication failed",
                },
                {
                    "status": "account_switched",
                    "profile_id": "27240",
                    "next_profile_id": "27273",
                    "error_code": "PROFILE_START_FAILED",
                    "error_message": "switch profile to 27273 after PROFILE_START_FAILED",
                },
            ],
            [{"profile_id": "27240"}, {"profile_id": "27273"}],
        )

        self.assertEqual(diagnostics["error_counts"]["PROFILE_START_FAILED"], 1)
        self.assertEqual(diagnostics["classification_counts"]["profile_start_failed"], 1)
        self.assertEqual(diagnostics["classification_counts"]["socks5_auth_failed"], 1)
        self.assertEqual(diagnostics["account_switches"][0]["profile_id"], "27240")
        self.assertEqual(diagnostics["account_switches"][0]["next_profile_id"], "27273")

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
        self.assertFalse(result["execution_evidence_policy"]["accept_fixture_uri"])
        self.assertEqual(result["execution_evidence_policy"]["failure_error_code"], "LIVE_SUBMIT_EVIDENCE_MISSING")

    def test_reachops_live_readiness_reports_missing_inputs_without_browser_or_submit(self):
        class Args:
            profile_ids = ""
            group_name = "AUDIT"
            video_url = ""
            follow_profile_url = ""
            dm_profile_url = ""
            target_username = ""
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
        self.assertFalse(checks["profile_ids_present"]["passed"])
        self.assertFalse(checks["profile_ids_are_ixbrowser_numeric_ids"]["passed"])
        self.assertFalse(checks["comment_video_url_valid"]["passed"])
        self.assertFalse(checks["follow_profile_url_valid"]["passed"])
        self.assertFalse(checks["dm_profile_url_valid"]["passed"])
        self.assertFalse(checks["target_username_matches_profiles"]["passed"])

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
            self.assertFalse(result["execution_evidence_policy"]["accept_fixture_uri"])
            self.assertIn("sidecar_screenshot_sha256_matches_file", result["execution_evidence_policy"]["local_file_requirements"])
            self.assertIn("sidecar_profile_id_present", result["execution_evidence_policy"]["local_file_requirements"])
            self.assertIn("sidecar_action_id_present", result["execution_evidence_policy"]["local_file_requirements"])
            self.assertIn("sidecar_current_url_present", result["execution_evidence_policy"]["local_file_requirements"])

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

    def test_reachops_activation_status_check_reports_device_and_capabilities(self):
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

            result = check_reachops_activation_status(activation_path)

            self.assertTrue(result["ready"])
            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["no_browser_started"])
            self.assertTrue(result["no_submit"])
            self.assertTrue(result["current_device_id"])
            checks = {item["name"]: item for item in result["checks"]}
            self.assertTrue(checks["activation_active"]["passed"])
            self.assertTrue(checks["device_binding_matches"]["passed"])
            self.assertTrue(checks["authorization_allows_live_actions"]["passed"])

    def test_reachops_activation_status_check_blocks_device_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            activation_path = Path(tmp) / "reachops_activation_status.json"
            activation_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "device_id": "another-device",
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            result = check_reachops_activation_status(activation_path)

            self.assertFalse(result["ready"])
            checks = {item["name"]: item for item in result["checks"]}
            self.assertFalse(checks["device_binding_matches"]["passed"])
            decisions = checks["authorization_allows_live_actions"]["evidence"]["decisions"]
            self.assertTrue(all(item["error_code"] == "LIVE_SUBMIT_DEVICE_MISMATCH" for item in decisions))

    def test_reachops_activation_status_template_is_not_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Args:
                active = True
                bind_current_device = True
                enable_live_submit = True
                enable_comment_reply = True
                enable_follow_review = True
                enable_dm_review = True
                license_tier = "enterprise"
                expires_at = "2999-01-01T00:00:00Z"
                days = 7

            activation_path = Path(tmp) / "reachops_activation_status.json"
            payload = build_reachops_activation_status_template(Args())
            self.assertIn("entitlement_id", payload)
            self.assertIn("issued_at", payload)
            self.assertIn("device_registration", payload)
            self.assertIn("offline_grace_until", payload)
            self.assertIn("audit", payload)
            self.assertIn("entitlement_signature", payload)
            activation_path.write_text(json.dumps(payload), encoding="utf-8")

            result = check_reachops_activation_status(activation_path)

            self.assertFalse(result["ready"])
            checks = {item["name"]: item for item in result["checks"]}
            self.assertFalse(checks["activation_not_template"]["passed"])
            decisions = checks["authorization_allows_live_actions"]["evidence"]["decisions"]
            self.assertTrue(all(item["error_code"] == "LIVE_SUBMIT_NOT_AUTHORIZED" for item in decisions))
            self.assertTrue(all("template" in item["error_message"] for item in decisions))

    def test_reachops_cross_platform_acceptance_input_init_writes_literal_windows_path(self):
        args = type(
            "Args",
            (),
            {
                "profile_group": "United States",
                "profile_ids": "p1,p2",
                "target": "anti aging serum",
                "comment_video_url": "https://www.tiktok.com/@creator/video/999",
                "follow_profile_url": "https://www.tiktok.com/@target",
                "dm_profile_url": "https://www.tiktok.com/@target",
                "target_username": "target",
                "activation_status_path": "C:\a" + "ctivation" + "\r" + "eachops_activation_status.json",
                "confirm_authorized_targets": True,
            },
        )()

        content = build_reachops_acceptance_inputs_content(args)

        self.assertIn('$ProfileGroup = "United States"', content)
        self.assertIn('$ProfileIds = "p1,p2"', content)
        self.assertIn('$CommentVideoUrl = "https://www.tiktok.com/@creator/video/999"', content)
        self.assertIn('$ActivationStatusPath = "C:\\activation\\reachops_activation_status.json"', content)
        self.assertIn("$ConfirmAuthorizedTargets = $true", content)
        self.assertNotIn("\a", content)
        self.assertNotIn("\r", content)

    def test_reachops_acceptance_input_init_json_reports_field_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "reachops_acceptance_inputs.local.ps1"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                exit_code = init_reachops_acceptance_inputs_main(
                    [
                        "--output-path",
                        str(output_path),
                        "--profile-ids",
                        "123,456,789",
                        "--comment-video-url",
                        "https://www.tiktok.com/@creator/video/123",
                        "--json",
                    ]
                )

            payload = json.loads(buffer.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            self.assertEqual(payload["status"], "created")
            self.assertTrue(payload["no_browser_started"])
            self.assertTrue(payload["no_submit"])
            self.assertFalse(payload["local_inputs"]["usable"])
            self.assertIn("ProfileIds", payload["local_inputs"]["placeholder_fields"])
            self.assertEqual(payload["local_inputs"]["field_status"]["ProfileIds"]["state"], "placeholder")
            self.assertEqual(
                payload["local_inputs"]["field_status"]["ConfirmAuthorizedTargets"]["state"],
                "authorization_not_confirmed",
            )
            self.assertIn(
                "python tools\\reachops_live_acceptance_status.py --write-report --json",
                payload["verification_commands"],
            )
            self.assertIn("python tools\\reachops_goal_delivery_runner.py --json", payload["verification_commands"])
            self.assertIn("python tools\\reachops_issue_closure_audit.py --json", payload["verification_commands"])

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

    def test_reachops_live_validation_manifest_rejects_activation_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "activation.json"
            payload = build_reachops_activation_status_template(type("Args", (), {
                "bind_current_device": True,
                "enable_live_submit": True,
                "enable_comment_reply": True,
                "enable_follow_review": True,
                "enable_dm_review": True,
                "days": 7,
            })())
            status_path.write_text(json.dumps(payload), encoding="utf-8")

            class Args:
                profile_group = "BR"
                profile_ids = "12345"
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

            self.assertEqual(manifest["status"], "blocked")
            self.assertIn("有效激活状态文件", manifest["missing_inputs"])
            self.assertFalse(manifest["blocking_summary"]["activation_ready"])
            self.assertTrue(manifest["activation_status"]["exists"])
            self.assertFalse(manifest["activation_status"]["ready"])
            checks = {item["name"]: item for item in manifest["activation_status"]["checks"]}
            self.assertFalse(checks["activation_not_template"]["passed"])

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

    def test_reachops_live_acceptance_status_summarizes_remaining_live_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            activation_path = tmp_path / "missing_activation.json"
            template_path = tmp_path / "reachops_activation_status.template.json"
            template_path.write_text("{}", encoding="utf-8")
            acceptance_dir = tmp_path / "reports" / "reachops_acceptance" / "20260625_092516"
            acceptance_dir.mkdir(parents=True)
            (acceptance_dir / "acceptance_summary.json").write_text(
                json.dumps(
                    {
                        "status": "ready_for_external_validation",
                        "delivery_audit": {"effective_pending_external_validation": 3},
                        "goal_status": {"pending_external_validation": ["授权允许时能真实执行", "真实 TikTok 平台提交", "客户端交付验收门禁不会把环境阻断当通过"]},
                        "pending_external_validation": ["授权允许时能真实执行", "真实 TikTok 平台提交", "客户端交付验收门禁不会把环境阻断当通过"],
                    }
                ),
                encoding="utf-8",
            )
            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps({"status": "ready_for_external_validation", "passed": True}),
                encoding="utf-8",
            )

            class Args:
                profile_group = "BR"
                profile_ids = "12345,67890"
                profile_limit = 3
                max_pages = 1
                profile_scan_timeout = 1
                target = "anti aging serum"
                comment_video_url = ""
                target_profile_url = ""
                dm_profile_url = ""
                target_username = ""
                activation_status_path = str(activation_path)
                activation_template_path = str(template_path)
                local_inputs_path = str(tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1")
                acceptance_reports_dir = str(tmp_path / "reports" / "reachops_acceptance")
                limit = 3
                allow_pressure_submit = ""
                confirm_authorized_targets = False

            status = build_reachops_live_acceptance_status(Args())

            self.assertEqual(status["status"], "blocked")
            self.assertFalse(status["ready_for_live_preflight"])
            self.assertFalse(status["final_delivery_ready"])
            self.assertFalse(status["local_inputs"]["exists"])
            self.assertTrue(status["activation"]["template_exists"])
            self.assertFalse(status["activation"]["ready"])
            self.assertEqual(status["live_validation"]["selected_profile_ids"], ["12345", "67890"])
            self.assertIn("本地验收输入文件 tools/reachops_acceptance_inputs.local.ps1", status["live_validation"]["missing_inputs"])
            self.assertIn("激活状态文件", status["live_validation"]["missing_inputs"])
            self.assertTrue(status["latest_acceptance"]["summary_exists"])
            self.assertTrue(status["latest_acceptance"]["package_check_exists"])
            self.assertFalse(status["latest_acceptance"]["package_final_delivery_ready"])
            self.assertFalse(status["latest_acceptance"]["final_acceptance_gate_exists"])
            self.assertEqual(status["latest_acceptance"]["effective_pending_external_validation"], 3)
            self.assertIn("live_validation:inputs", status["failed_checks"])
            self.assertIn("local_inputs:usable", status["failed_checks"])
            self.assertIn("activation:ready", status["failed_checks"])
            self.assertIn("delivery_package:final_delivery_ready", status["failed_checks"])
            self.assertIn("本地验收输入文件 tools/reachops_acceptance_inputs.local.ps1", status["blocked_reasons"])
            self.assertIn("Windows 交付包未达到 final_delivery_ready=true。", status["blocked_reasons"])
            plan = {row["stage"]: row for row in status["blocking_plan"]}
            self.assertEqual(plan["授权输入"]["status"], "blocked")
            self.assertIn("本地验收输入文件 tools/reachops_acceptance_inputs.local.ps1", plan["授权输入"]["blockers"])
            self.assertEqual(plan["激活状态"]["status"], "blocked")
            self.assertEqual(plan["Windows交付包"]["status"], "blocked")
            self.assertTrue(any("acceptance_summary.json" in item for item in plan["Windows交付包"]["blockers"]))
            self.assertEqual(plan["最终门禁"]["status"], "blocked")
            self.assertIn(
                "运行 tools\\reachops_final_acceptance_gate.py --json 并确认 status=passed、final_delivery_ready=true。",
                plan["最终门禁"]["actions"],
            )
            self.assertEqual(status["next_required_actions"][0], "运行 tools\\init_reachops_acceptance_inputs_windows.ps1 生成本地验收输入文件，然后填入已授权 TikTok 目标和激活状态路径。")
            self.assertIn(
                "powershell -ExecutionPolicy Bypass -File tools\\init_reachops_acceptance_inputs_windows.ps1 -Json",
                status["operator_commands"],
            )
            self.assertIn(
                "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -InputFile tools\\reachops_acceptance_inputs.local.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
                status["operator_commands"],
            )
            self.assertEqual(
                status["verification_commands"],
                [
                    "python tools\\reachops_client_delivery_check.py --json",
                    "python tools\\reachops_goal_delivery_runner.py --json",
                    "python tools\\reachops_delivery_package_check.py --json",
                    "python tools\\reachops_issue_closure_audit.py --json",
                    "python tools\\reachops_final_acceptance_gate.py --json",
                ],
            )

    def test_reachops_live_acceptance_status_blocks_placeholder_local_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_inputs_path = tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1"
            local_inputs_path.parent.mkdir(parents=True)
            local_inputs_path.write_text(
                "\n".join(
                    [
                        '$ProfileIds = "123,456,789"',
                        '$CommentVideoUrl = "https://www.tiktok.com/@creator/video/123"',
                        '$FollowProfileUrl = "https://www.tiktok.com/@target_user"',
                        '$DmProfileUrl = "https://www.tiktok.com/@target_user"',
                        '$TargetUsername = "target_user"',
                        '$ActivationStatusPath = "C:\\path\\to\\reachops_activation_status.json"',
                    ]
                ),
                encoding="utf-8",
            )

            args = type(
                "Args",
                (),
                {
                    "profile_group": "BR",
                    "profile_ids": "",
                    "profile_limit": 3,
                    "max_pages": 1,
                    "profile_scan_timeout": 1,
                    "target": "anti aging serum",
                    "comment_video_url": "",
                    "target_profile_url": "",
                    "dm_profile_url": "",
                    "target_username": "",
                    "activation_status_path": "",
                    "activation_template_path": "",
                    "local_inputs_path": str(local_inputs_path),
                    "acceptance_reports_dir": str(tmp_path / "reports" / "reachops_acceptance"),
                    "limit": 3,
                    "allow_pressure_submit": "",
                    "confirm_authorized_targets": False,
                },
            )()

            status = build_reachops_live_acceptance_status(args)

            self.assertTrue(status["local_inputs"]["exists"])
            self.assertFalse(status["local_inputs"]["usable"])
            self.assertIn("ProfileIds", status["local_inputs"]["placeholder_fields"])
            self.assertIn("ActivationStatusPath", status["local_inputs"]["placeholder_fields"])
            self.assertEqual(status["local_inputs"]["field_status"]["ProfileIds"]["state"], "placeholder")
            self.assertEqual(
                status["local_inputs"]["field_status"]["ConfirmAuthorizedTargets"]["state"],
                "authorization_not_confirmed",
            )
            self.assertEqual(status["live_validation"]["selected_profile_ids"], [])
            self.assertEqual(status["live_validation"]["selected_profile_count"], 0)
            self.assertIn("本地验收输入文件仍有占位值或缺失字段", status["live_validation"]["missing_inputs"])
            self.assertIn("ixBrowser 数字 Profile ID", status["live_validation"]["missing_inputs"])
            self.assertIn("生成或放置真实激活状态文件，并设置 ActivationStatusPath。", status["next_required_actions"])
            self.assertTrue(status["activation"]["failed_checks"])
            plan = {row["stage"]: row for row in status["blocking_plan"]}
            self.assertIn(
                "先在 Windows 实机运行 tools\\run_reachops_acceptance_windows.ps1 生成 acceptance_summary.json 和 final_acceptance_gate.json。",
                plan["最终门禁"]["actions"],
            )
            self.assertIn(
                "再运行 tools\\reachops_final_acceptance_gate.py --json 并确认 status=passed、final_delivery_ready=true。",
                plan["最终门禁"]["actions"],
            )

    def test_reachops_live_acceptance_status_marks_template_activation_path_as_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            activation_path = tmp_path / "reachops_activation_status.template.json"
            activation_path.write_text(json.dumps({"template_only": True}), encoding="utf-8")
            local_inputs_path = tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1"
            local_inputs_path.parent.mkdir(parents=True)
            local_inputs_path.write_text(
                "\n".join(
                    [
                        '$ProfileIds = "24964,24958"',
                        '$CommentVideoUrl = "https://www.tiktok.com/@creator/video/999"',
                        '$FollowProfileUrl = "https://www.tiktok.com/@authorized_user"',
                        '$DmProfileUrl = "https://www.tiktok.com/@authorized_user"',
                        '$TargetUsername = "authorized_user"',
                        f'$ActivationStatusPath = "{activation_path}"',
                        "$ConfirmAuthorizedTargets = $true",
                    ]
                ),
                encoding="utf-8",
            )

            status = build_reachops_live_acceptance_status(
                type(
                    "Args",
                    (),
                    {
                        "profile_group": "United States",
                        "profile_ids": "",
                        "profile_limit": 3,
                        "max_pages": 1,
                        "profile_scan_timeout": 1,
                        "target": "anti aging serum",
                        "comment_video_url": "",
                        "target_profile_url": "",
                        "dm_profile_url": "",
                        "target_username": "",
                        "activation_status_path": "",
                        "activation_template_path": "",
                        "local_inputs_path": str(local_inputs_path),
                        "acceptance_reports_dir": str(tmp_path / "reports" / "reachops_acceptance"),
                        "limit": 3,
                        "allow_pressure_submit": "",
                        "confirm_authorized_targets": False,
                    },
                )()
            )

            self.assertFalse(status["local_inputs"]["usable"])
            self.assertIn("ActivationStatusPath", status["local_inputs"]["placeholder_fields"])
            self.assertEqual(status["local_inputs"]["field_status"]["ActivationStatusPath"]["state"], "placeholder")
            self.assertIn("local_inputs:usable", status["failed_checks"])
            self.assertIn("activation:ready", status["failed_checks"])

    def test_reachops_live_acceptance_status_writes_operator_readiness_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_inputs_path = tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1"
            local_inputs_path.parent.mkdir(parents=True)
            local_inputs_path.write_text(
                "\n".join(
                    [
                        '$ProfileIds = "123,456,789"',
                        '$Target = "anti aging serum"',
                        '$CommentVideoUrl = "https://www.tiktok.com/@creator/video/123"',
                        '$FollowProfileUrl = "https://www.tiktok.com/@target_user"',
                        '$DmProfileUrl = "https://www.tiktok.com/@target_user"',
                        '$TargetUsername = "target_user"',
                        '$ActivationStatusPath = "C:\\path\\to\\reachops_activation_status.json"',
                        "$ConfirmAuthorizedTargets = $false",
                    ]
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "profile_group": "BR",
                    "profile_ids": "",
                    "profile_limit": 3,
                    "max_pages": 1,
                    "profile_scan_timeout": 1,
                    "target": "",
                    "comment_video_url": "",
                    "target_profile_url": "",
                    "dm_profile_url": "",
                    "target_username": "",
                    "activation_status_path": "",
                    "activation_template_path": "",
                    "local_inputs_path": str(local_inputs_path),
                    "acceptance_reports_dir": str(tmp_path / "reports" / "reachops_acceptance"),
                    "limit": 3,
                    "allow_pressure_submit": "",
                    "confirm_authorized_targets": False,
                },
            )()

            status = build_reachops_live_acceptance_status(args)
            markdown = render_reachops_live_acceptance_report(status)
            report_path = write_reachops_live_acceptance_report(status, tmp_path / "latest_live_acceptance_readiness.md")
            json_report_path = write_reachops_live_acceptance_json_report(
                status,
                tmp_path / "latest_live_acceptance_readiness.json",
            )

            self.assertTrue(report_path.exists())
            self.assertTrue(json_report_path.exists())
            json_report = json.loads(json_report_path.read_text(encoding="utf-8"))
            self.assertEqual(json_report["status"], "blocked")
            self.assertEqual(json_report["json_report_path"], str(json_report_path))
            self.assertIn("operator_commands", json_report)
            self.assertIn("ReachOps Live Acceptance Readiness", markdown)
            self.assertIn("| ProfileIds | placeholder |", markdown)
            self.assertIn("| ConfirmAuthorizedTargets | authorization_not_confirmed |", markdown)
            self.assertIn("activation_status_file_exists", markdown)
            self.assertIn("授权输入 / blocked", markdown)
            self.assertIn("## Operator Command Sequence", markdown)
            self.assertIn("init_reachops_acceptance_inputs_windows.ps1 -Json", markdown)
            self.assertIn("--write-report --json-report-path --json", markdown)
            self.assertIn("-InputFile tools\\reachops_acceptance_inputs.local.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets", markdown)
            self.assertIn("python tools\\reachops_final_acceptance_gate.py --json", markdown)
            self.assertEqual(report_path.read_text(encoding="utf-8"), markdown)

    def test_reachops_authorization_handoff_bundle_excludes_local_secret_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_inputs_path = tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1"
            local_inputs_path.parent.mkdir(parents=True)
            local_inputs_path.write_text(
                "\n".join(
                    [
                        '$ProfileIds = "123,456,789"',
                        '$Target = "anti aging serum"',
                        '$CommentVideoUrl = "https://www.tiktok.com/@creator/video/123"',
                        '$FollowProfileUrl = "https://www.tiktok.com/@target_user"',
                        '$DmProfileUrl = "https://www.tiktok.com/@target_user"',
                        '$TargetUsername = "target_user"',
                        '$ActivationStatusPath = "C:\\path\\to\\reachops_activation_status.json"',
                        "$ConfirmAuthorizedTargets = $false",
                    ]
                ),
                encoding="utf-8",
            )
            bundle_path = tmp_path / "reachops_authorization_handoff.zip"
            (tmp_path / "latest_phase2_handoff_check.md").write_text(
                "# ReachOps Phase 2 Handoff Check\n\n- ready_for_windows_execution: `true`\n",
                encoding="utf-8",
            )
            (tmp_path / "latest_phase2_handoff_check.json").write_text(
                json.dumps(
                    {
                        "status": "ready_for_windows_execution",
                        "live_readiness": {
                            "local_inputs": {
                                "path": str(local_inputs_path),
                                "usable": False,
                                "placeholder_fields": ["ProfileIds"],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_reachops_authorization_handoff_bundle(
                type(
                    "Args",
                    (),
                    {
                        "output_path": str(bundle_path),
                        "profile_group": "BR",
                        "profile_ids": "",
                        "profile_limit": 3,
                        "max_pages": 1,
                        "profile_scan_timeout": 1,
                        "target": "",
                        "comment_video_url": "",
                        "target_profile_url": "",
                        "dm_profile_url": "",
                        "target_username": "",
                        "activation_status_path": "",
                        "activation_template_path": "",
                        "local_inputs_path": str(local_inputs_path),
                        "acceptance_reports_dir": str(tmp_path / "reports" / "reachops_acceptance"),
                        "limit": 3,
                        "allow_pressure_submit": "",
                        "confirm_authorized_targets": False,
                    },
                )()
            )

            self.assertTrue(result["exists"])
            self.assertGreater(result["size"], 0)
            self.assertFalse(result["final_delivery_ready"])
            with zipfile.ZipFile(bundle_path) as zf:
                names = set(zf.namelist())
                self.assertIn("README_AUTHORIZATION_HANDOFF.md", names)
                self.assertIn("latest_live_acceptance_readiness.md", names)
                self.assertIn("latest_live_acceptance_readiness.json", names)
                self.assertIn("latest_phase2_handoff_check.md", names)
                self.assertIn("latest_phase2_handoff_check.json", names)
                self.assertIn("authorization_handoff_commands.txt", names)
                self.assertIn("authorization_handoff_manifest.json", names)
                self.assertIn("reachops_acceptance_inputs.example.ps1", names)
                self.assertNotIn("reachops_acceptance_inputs.local.ps1", names)
                manifest = json.loads(zf.read("authorization_handoff_manifest.json").decode("utf-8"))
                self.assertIn("latest_phase2_handoff_check.md", manifest["included_files"])
                self.assertIn("latest_phase2_handoff_check.json", manifest["included_files"])
                self.assertIn("tools/reachops_acceptance_inputs.local.ps1", manifest["excluded_sensitive_files"])
                self.assertEqual(
                    manifest["commercial_issue_closure_command"],
                    "python tools\\reachops_issue_closure_audit.py --json",
                )
                self.assertIn("reachops_issue_closure_audit.py --json", "\n".join(manifest["verification_commands"]))
                readme = zf.read("README_AUTHORIZATION_HANDOFF.md").decode("utf-8")
                self.assertIn("commercial_issue_closure_command", readme)
                self.assertIn("reachops_issue_closure_audit.py --json", readme)
                commands = zf.read("authorization_handoff_commands.txt").decode("utf-8")
                self.assertIn("init_reachops_acceptance_inputs_windows.ps1 -Json", commands)
                self.assertIn("reachops_issue_closure_audit.py --json", commands)
                self.assertIn("reachops_final_acceptance_gate.py --json", commands)
            verified = verify_reachops_authorization_handoff_bundle(bundle_path)
            self.assertTrue(verified["passed"])
            self.assertFalse(verified["failures"])
            self.assertEqual(verified["forbidden_files"], [])

            broken_bundle = tmp_path / "broken_handoff.zip"
            with zipfile.ZipFile(broken_bundle, "w") as zf:
                zf.writestr("reachops_acceptance_inputs.local.ps1", "real values must not be bundled")
            broken = verify_reachops_authorization_handoff_bundle(broken_bundle)
            self.assertFalse(broken["passed"])
            self.assertIn("required_files_missing", broken["failures"])
            self.assertIn("forbidden_sensitive_files_included", broken["failures"])

            stale_bundle = tmp_path / "stale_handoff.zip"
            with zipfile.ZipFile(stale_bundle, "w") as zf:
                for name in (
                    "README_AUTHORIZATION_HANDOFF.md",
                    "latest_live_acceptance_readiness.md",
                    "latest_live_acceptance_readiness.json",
                    "latest_phase2_handoff_check.md",
                    "latest_phase2_handoff_check.json",
                    "authorization_handoff_commands.txt",
                    "authorization_handoff_manifest.json",
                    "reachops_acceptance_inputs.example.ps1",
                ):
                    if name.endswith(".json"):
                        payload = {
                            "excluded_sensitive_files": ["tools/reachops_acceptance_inputs.local.ps1"],
                            "no_browser_started": True,
                            "no_submit": True,
                            "operator_commands": ["powershell -ExecutionPolicy Bypass -File tools\\init_reachops_acceptance_inputs_windows.ps1 -Json"],
                            "verification_commands": ["python tools\\reachops_final_acceptance_gate.py --json"],
                        }
                        if name == "latest_phase2_handoff_check.json":
                            payload = {"live_readiness": {"local_inputs": {"usable": False}}}
                        zf.writestr(name, json.dumps(payload))
                    elif name == "authorization_handoff_commands.txt":
                        zf.writestr(
                            name,
                            "\n".join(
                                [
                                    "powershell -ExecutionPolicy Bypass -File tools\\init_reachops_acceptance_inputs_windows.ps1 -Json",
                                    "python tools\\reachops_final_acceptance_gate.py --json",
                                ]
                            ),
                        )
                    else:
                        zf.writestr(name, "placeholder")
            stale = verify_reachops_authorization_handoff_bundle(stale_bundle)
            self.assertFalse(stale["passed"])
            self.assertIn("issue_closure_command_missing", stale["failures"])
            self.assertIn("issue_closure_command_not_declared", stale["failures"])

    def test_reachops_live_acceptance_status_reads_filled_local_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            activation_path = tmp_path / "reachops_activation_status.json"
            payload = build_reachops_activation_status_template(
                type(
                    "Args",
                    (),
                    {
                        "active": True,
                        "bind_current_device": True,
                        "enable_live_submit": True,
                        "enable_comment_reply": True,
                        "enable_follow_review": True,
                        "enable_dm_review": True,
                        "license_tier": "enterprise",
                        "expires_at": "2999-01-01T00:00:00Z",
                        "days": 7,
                    },
                )()
            )
            payload["template_only"] = False
            activation_path.write_text(json.dumps(payload), encoding="utf-8")
            local_inputs_path = tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1"
            local_inputs_path.parent.mkdir(parents=True)
            local_inputs_path.write_text(
                "\n".join(
                    [
                        '$ProfileIds = "27273,27240"',
                        '$Target = "anti aging serum"',
                        '$CommentVideoUrl = "https://www.tiktok.com/@creator/video/987654321"',
                        '$FollowProfileUrl = "https://www.tiktok.com/@buyer_one"',
                        '$DmProfileUrl = "https://www.tiktok.com/@buyer_one"',
                        '$TargetUsername = "buyer_one"',
                        f'$ActivationStatusPath = "{activation_path}"',
                        "$ConfirmAuthorizedTargets = $true",
                    ]
                ),
                encoding="utf-8",
            )

            args = type(
                "Args",
                (),
                {
                    "profile_group": "BR",
                    "profile_ids": "",
                    "profile_limit": 3,
                    "max_pages": 1,
                    "profile_scan_timeout": 1,
                    "target": "",
                    "comment_video_url": "",
                    "target_profile_url": "",
                    "dm_profile_url": "",
                    "target_username": "",
                    "activation_status_path": "",
                    "activation_template_path": "",
                    "local_inputs_path": str(local_inputs_path),
                    "acceptance_reports_dir": str(tmp_path / "reports" / "reachops_acceptance"),
                    "limit": 3,
                    "allow_pressure_submit": "",
                    "confirm_authorized_targets": True,
                },
            )()

            status = build_reachops_live_acceptance_status(args)

            self.assertTrue(status["local_inputs"]["usable"])
            self.assertEqual(status["local_inputs"]["placeholder_fields"], [])
            self.assertEqual(status["live_validation"]["selected_profile_ids"], ["27273", "27240"])
            self.assertTrue(status["activation"]["ready"])
            self.assertEqual(status["activation"]["failed_checks"], [])
            self.assertEqual(status["activation"]["next_required_actions"], [])
            self.assertTrue(status["ready_for_live_preflight"])
            self.assertEqual(status["next_required_actions"], ["运行受控真实提交并生成 live submit evidence"])
            self.assertIn("python tools\\reachops_goal_delivery_runner.py --json", status["verification_commands"])
            self.assertIn("python tools\\reachops_issue_closure_audit.py --json", status["verification_commands"])
            self.assertIn("python tools\\reachops_final_acceptance_gate.py --json", status["verification_commands"])

    def test_reachops_live_acceptance_status_expands_latest_pending_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            activation_path = tmp_path / "reachops_activation_status.json"
            payload = build_reachops_activation_status_template(
                type(
                    "Args",
                    (),
                    {
                        "active": True,
                        "bind_current_device": True,
                        "enable_live_submit": True,
                        "enable_comment_reply": True,
                        "enable_follow_review": True,
                        "enable_dm_review": True,
                        "license_tier": "enterprise",
                        "expires_at": "2999-01-01T00:00:00Z",
                        "days": 7,
                    },
                )()
            )
            payload["template_only"] = False
            activation_path.write_text(json.dumps(payload), encoding="utf-8")
            local_inputs_path = tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1"
            local_inputs_path.parent.mkdir(parents=True)
            local_inputs_path.write_text(
                "\n".join(
                    [
                        '$ProfileIds = "27273,27240"',
                        '$Target = "anti aging serum"',
                        '$CommentVideoUrl = "https://www.tiktok.com/@creator/video/987654321"',
                        '$FollowProfileUrl = "https://www.tiktok.com/@buyer_one"',
                        '$DmProfileUrl = "https://www.tiktok.com/@buyer_one"',
                        '$TargetUsername = "buyer_one"',
                        f'$ActivationStatusPath = "{activation_path}"',
                        "$ConfirmAuthorizedTargets = $true",
                    ]
                ),
                encoding="utf-8",
            )
            acceptance_dir = tmp_path / "reports" / "reachops_acceptance" / "20260629_010101"
            acceptance_dir.mkdir(parents=True)
            (acceptance_dir / "acceptance_summary.json").write_text(
                json.dumps(
                    {
                        "status": "ready_for_external_validation",
                        "delivery_audit": {"effective_pending_external_validation": 3},
                        "goal_status": {
                            "pending_external_validation": [
                                "授权允许时能真实执行",
                                "真实 TikTok 平台提交",
                                "客户端交付验收门禁不会把环境阻断当通过",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            args = type(
                "Args",
                (),
                {
                    "profile_group": "BR",
                    "profile_ids": "",
                    "profile_limit": 3,
                    "max_pages": 1,
                    "profile_scan_timeout": 1,
                    "target": "",
                    "comment_video_url": "",
                    "target_profile_url": "",
                    "dm_profile_url": "",
                    "target_username": "",
                    "activation_status_path": "",
                    "activation_template_path": "",
                    "local_inputs_path": str(local_inputs_path),
                    "acceptance_reports_dir": str(tmp_path / "reports" / "reachops_acceptance"),
                    "limit": 3,
                    "allow_pressure_submit": "",
                    "confirm_authorized_targets": True,
                },
            )()

            status = build_reachops_live_acceptance_status(args)

            self.assertTrue(status["ready_for_live_preflight"])
            self.assertIn("运行 readiness/preflight 后执行受控真实提交，确认授权目标和激活状态通过。", status["next_required_actions"])
            self.assertIn("使用真实 ixBrowser Profile 和授权 TikTok 目标完成 platform_selenium live submit。", status["next_required_actions"])
            self.assertIn("重新运行客户端交付验收，直到 acceptance_ready=true 且 readiness=pass。", status["next_required_actions"])

    def test_reachops_live_acceptance_status_requires_latest_final_gate_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            activation_path = tmp_path / "reachops_activation_status.json"
            payload = build_reachops_activation_status_template(
                type(
                    "Args",
                    (),
                    {
                        "active": True,
                        "bind_current_device": True,
                        "enable_live_submit": True,
                        "enable_comment_reply": True,
                        "enable_follow_review": True,
                        "enable_dm_review": True,
                        "license_tier": "enterprise",
                        "expires_at": "2999-01-01T00:00:00Z",
                        "days": 7,
                    },
                )()
            )
            payload["template_only"] = False
            activation_path.write_text(json.dumps(payload), encoding="utf-8")
            local_inputs_path = tmp_path / "tools" / "reachops_acceptance_inputs.local.ps1"
            local_inputs_path.parent.mkdir(parents=True)
            local_inputs_path.write_text(
                "\n".join(
                    [
                        '$ProfileIds = "27273,27240"',
                        '$Target = "anti aging serum"',
                        '$CommentVideoUrl = "https://www.tiktok.com/@creator/video/987654321"',
                        '$FollowProfileUrl = "https://www.tiktok.com/@buyer_one"',
                        '$DmProfileUrl = "https://www.tiktok.com/@buyer_one"',
                        '$TargetUsername = "buyer_one"',
                        f'$ActivationStatusPath = "{activation_path}"',
                        "$ConfirmAuthorizedTargets = $true",
                    ]
                ),
                encoding="utf-8",
            )
            acceptance_dir = tmp_path / "reports" / "reachops_acceptance" / "20260629_020202"
            acceptance_dir.mkdir(parents=True)
            summary = {
                "status": "passed",
                "delivery_audit": {"effective_pending_external_validation": 0},
                "goal_status": {"pending_external_validation": []},
                "final_acceptance_gate": {
                    "status": "not_ready",
                    "final_delivery_ready": False,
                    "failed_checks": ["delivery_package:passed"],
                    "next_actions": ["Build Windows exe/installer/manifest and regenerate a passed acceptance_summary.json, then rerun delivery package check."],
                },
            }
            (acceptance_dir / "acceptance_summary.json").write_text(json.dumps(summary), encoding="utf-8")
            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "passed": True,
                        "final_delivery_ready": False,
                        "bootstrap_only": True,
                        "not_final_delivery_reasons": ["allow_missing_final_gate is bootstrap-only"],
                    }
                ),
                encoding="utf-8",
            )

            args = type(
                "Args",
                (),
                {
                    "profile_group": "BR",
                    "profile_ids": "",
                    "profile_limit": 3,
                    "max_pages": 1,
                    "profile_scan_timeout": 1,
                    "target": "",
                    "comment_video_url": "",
                    "target_profile_url": "",
                    "dm_profile_url": "",
                    "target_username": "",
                    "activation_status_path": "",
                    "activation_template_path": "",
                    "local_inputs_path": str(local_inputs_path),
                    "acceptance_reports_dir": str(tmp_path / "reports" / "reachops_acceptance"),
                    "limit": 3,
                    "allow_pressure_submit": "",
                    "confirm_authorized_targets": True,
                },
            )()

            blocked = build_reachops_live_acceptance_status(args)
            self.assertFalse(blocked["final_delivery_ready"])
            self.assertEqual(blocked["latest_acceptance"]["final_gate_status"], "not_ready")
            self.assertFalse(blocked["latest_acceptance"]["final_acceptance_gate_exists"])
            self.assertEqual(blocked["latest_acceptance"]["final_gate_failed_checks"], ["delivery_package:passed"])
            self.assertFalse(blocked["latest_acceptance"]["package_final_delivery_ready"])
            self.assertTrue(blocked["latest_acceptance"]["package_bootstrap_only"])
            self.assertIn("delivery_package:final_delivery_ready", blocked["failed_checks"])
            self.assertIn("delivery_package:not_bootstrap", blocked["failed_checks"])
            self.assertIn("delivery_package:evidence", blocked["failed_checks"])
            self.assertIn("final_acceptance_gate:passed", blocked["failed_checks"])
            self.assertIn("final_gate:delivery_package:passed", blocked["failed_checks"])
            self.assertIn("Windows 交付包未达到 final_delivery_ready=true。", blocked["blocked_reasons"])
            self.assertIn("当前 package check 是 bootstrap-only，不能作为最终交付证据。", blocked["blocked_reasons"])
            self.assertEqual(
                blocked["next_required_actions"],
                ["Build Windows exe/installer/manifest and regenerate a passed acceptance_summary.json, then rerun delivery package check."],
            )

            summary["final_acceptance_gate"] = {"status": "passed", "final_delivery_ready": True, "failed_checks": []}
            (acceptance_dir / "acceptance_summary.json").write_text(json.dumps(summary), encoding="utf-8")
            (acceptance_dir / "final_acceptance_gate.json").write_text(json.dumps(summary["final_acceptance_gate"]), encoding="utf-8")

            bootstrap_blocked = build_reachops_live_acceptance_status(args)
            self.assertFalse(bootstrap_blocked["final_delivery_ready"])
            self.assertEqual(bootstrap_blocked["status"], "blocked")

            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps({"status": "passed", "passed": True, "final_delivery_ready": True, "bootstrap_only": False}),
                encoding="utf-8",
            )

            weak_package_blocked = build_reachops_live_acceptance_status(args)
            self.assertFalse(weak_package_blocked["final_delivery_ready"])
            self.assertFalse(weak_package_blocked["latest_acceptance"]["package_evidence_ready"])
            self.assertFalse(weak_package_blocked["latest_acceptance"]["package_root_matches"])
            self.assertFalse(weak_package_blocked["latest_acceptance"]["package_pe_artifacts_ready"])

            wrong_root_package = final_package_check_payload()
            wrong_root_package["root"] = str((tmp_path / "outside").resolve())
            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps(wrong_root_package),
                encoding="utf-8",
            )

            wrong_root_blocked = build_reachops_live_acceptance_status(args)
            self.assertFalse(wrong_root_blocked["final_delivery_ready"])
            self.assertFalse(wrong_root_blocked["latest_acceptance"]["package_evidence_ready"])
            self.assertFalse(wrong_root_blocked["latest_acceptance"]["package_root_matches"])
            self.assertIn("delivery_package:evidence", wrong_root_blocked["failed_checks"])

            final_package = final_package_check_payload()
            final_package["root"] = str(tmp_path.resolve())
            missing_issue_closure_report = json.loads(json.dumps(final_package))
            missing_issue_closure_report["report_files"].pop("issue_closure")
            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps(missing_issue_closure_report),
                encoding="utf-8",
            )

            missing_issue_closure_status = build_reachops_live_acceptance_status(args)
            self.assertFalse(missing_issue_closure_status["final_delivery_ready"])
            self.assertFalse(missing_issue_closure_status["latest_acceptance"]["package_evidence_ready"])
            self.assertFalse(missing_issue_closure_status["latest_acceptance"]["package_report_files_ready"])
            self.assertIn("delivery_package:evidence", missing_issue_closure_status["failed_checks"])

            missing_authorization_handoff_report = json.loads(json.dumps(final_package))
            missing_authorization_handoff_report["report_files"].pop("authorization_handoff")
            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps(missing_authorization_handoff_report),
                encoding="utf-8",
            )

            missing_authorization_handoff_status = build_reachops_live_acceptance_status(args)
            self.assertFalse(missing_authorization_handoff_status["final_delivery_ready"])
            self.assertFalse(missing_authorization_handoff_status["latest_acceptance"]["package_evidence_ready"])
            self.assertFalse(missing_authorization_handoff_status["latest_acceptance"]["package_report_files_ready"])
            self.assertIn("delivery_package:evidence", missing_authorization_handoff_status["failed_checks"])

            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps(final_package),
                encoding="utf-8",
            )

            passed = build_reachops_live_acceptance_status(args)
            self.assertTrue(passed["final_delivery_ready"])
            self.assertEqual(passed["status"], "passed")
            self.assertEqual(passed["blocked_reasons"], [])
            self.assertEqual(passed["failed_checks"], [])
            self.assertTrue(passed["latest_acceptance"]["final_acceptance_gate_exists"])
            self.assertTrue(passed["latest_acceptance"]["package_final_delivery_ready"])
            self.assertTrue(passed["latest_acceptance"]["package_evidence_ready"])
            self.assertTrue(passed["latest_acceptance"]["package_root_matches"])
            self.assertTrue(passed["latest_acceptance"]["package_pe_artifacts_ready"])
            self.assertTrue(passed["latest_acceptance"]["package_manifest_hash_ready"])
            self.assertTrue(passed["latest_acceptance"]["package_manifest_size_ready"])
            self.assertTrue(passed["latest_acceptance"]["package_final_gate_summary_ready"])

            missing_final_gate_report = dict(final_package)
            missing_final_gate_report.pop("final_gate_report", None)
            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps(missing_final_gate_report),
                encoding="utf-8",
            )

            missing_final_gate_report_status = build_reachops_live_acceptance_status(args)
            self.assertFalse(missing_final_gate_report_status["final_delivery_ready"])
            self.assertFalse(missing_final_gate_report_status["latest_acceptance"]["package_evidence_ready"])
            self.assertFalse(missing_final_gate_report_status["latest_acceptance"]["package_final_gate_summary_ready"])

            failed_final_gate_report = json.loads(json.dumps(final_package))
            failed_final_gate_report["final_gate_report"]["failed_required_checks"] = ["delivery_package:passed"]
            (acceptance_dir / "delivery_package_check.json").write_text(
                json.dumps(failed_final_gate_report),
                encoding="utf-8",
            )

            failed_final_gate_report_status = build_reachops_live_acceptance_status(args)
            self.assertFalse(failed_final_gate_report_status["final_delivery_ready"])
            self.assertFalse(failed_final_gate_report_status["latest_acceptance"]["package_evidence_ready"])
            self.assertFalse(failed_final_gate_report_status["latest_acceptance"]["package_final_gate_summary_ready"])

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

            class DynamicEvidenceExecutor:
                def execute(self, action, profile, rendered_text, dry_run=True):
                    action_type = str(action.get("action_type") or "")
                    path = evidence_dir / f"{action_type}.png"
                    path.write_bytes(b"png")
                    sidecar = {
                        "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                        "screenshot_size": 3,
                        "action_type": action_type,
                        "profile_id": str(profile.get("profile_id") or ""),
                        "action_id": str(action.get("id") or ""),
                        "current_url": str(action.get("target_url") or ""),
                    }
                    if action_type == "comment_reply":
                        sidecar["submitted_text"] = rendered_text
                        sidecar["comment_visible_confirmed"] = True
                    Path(f"{path}.json").write_text(json.dumps(sidecar), encoding="utf-8")
                    return {"status": "success", "error_code": "", "error_message": "", "evidence_path": str(path)}

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
                return_value=DynamicEvidenceExecutor(),
            ):
                result = run_reachops_live_submit_acceptance(Args())

            self.assertTrue(result["passed"])
            self.assertEqual(result["executor_mode"], "platform_selenium")
            self.assertTrue(result["platform_validation"])
            self.assertEqual(result["missing_local_evidence_file_action_types"], [])
            self.assertEqual(result["evidence_file_details"]["comment_reply"][0]["size"], 3)
            self.assertEqual(result["evidence_file_details"]["follow_review"][0]["sha256"], hashlib.sha256(b"png").hexdigest())
            self.assertTrue(result["evidence_file_details"]["dm_review"][0]["sidecar_path"].endswith(".png.json"))
            self.assertEqual(result["evidence_file_details"]["comment_reply"][0]["sidecar"]["profile_id"], "12345")
            self.assertIn(
                result["evidence_file_details"]["comment_reply"][0]["sidecar"]["action_id"],
                result["seeded_action_ids_by_type"]["comment_reply"],
            )

    def test_reachops_live_submit_acceptance_rejects_stale_action_or_profile_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence-fixture"
            evidence_dir.mkdir(parents=True, exist_ok=True)

            class StaleEvidenceExecutor:
                def execute(self, action, profile, rendered_text, dry_run=True):
                    action_type = str(action.get("action_type") or "")
                    path = evidence_dir / f"{action_type}.png"
                    path.write_bytes(b"png")
                    sidecar = {
                        "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                        "screenshot_size": 3,
                        "action_type": action_type,
                        "profile_id": str(profile.get("profile_id") or ""),
                        "action_id": str(action.get("id") or ""),
                        "current_url": str(action.get("target_url") or ""),
                    }
                    if action_type == "comment_reply":
                        sidecar["action_id"] = "aq_old_comment"
                        sidecar["submitted_text"] = rendered_text
                        sidecar["comment_visible_confirmed"] = True
                    if action_type == "follow_review":
                        sidecar["profile_id"] = "99999"
                    Path(f"{path}.json").write_text(json.dumps(sidecar), encoding="utf-8")
                    return {"status": "success", "error_code": "", "error_message": "", "evidence_path": str(path)}

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
                return_value=StaleEvidenceExecutor(),
            ):
                result = run_reachops_live_submit_acceptance(Args())

            self.assertFalse(result["passed"])
            self.assertIn("comment_reply", result["missing_local_evidence_file_action_types"])
            self.assertIn("follow_review", result["missing_local_evidence_file_action_types"])
            self.assertEqual(result["evidence_file_details"]["comment_reply"], [])
            self.assertEqual(result["evidence_file_details"]["follow_review"], [])
            self.assertTrue(result["evidence_file_details"]["dm_review"])

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

    def test_reachops_live_submit_acceptance_rejects_unconfirmed_comment_evidence(self):
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
                sidecar = {
                    "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                    "screenshot_size": 3,
                    "action_type": action_type,
                    "profile_id": "profile-a",
                    "action_id": f"{action_type}-1",
                    "current_url": "https://www.tiktok.com/@creator/video/123",
                }
                if action_type == "comment_reply":
                    sidecar["submitted_text"] = "authorized comment"
                    sidecar["comment_visible_confirmed"] = False
                Path(f"{path}.json").write_text(json.dumps(sidecar), encoding="utf-8")

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
            self.assertIn("comment_reply", result["missing_local_evidence_file_action_types"])
            self.assertEqual(result["evidence_file_details"]["comment_reply"], [])

    def test_reachops_packaging_files_define_standalone_windows_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "ReachOps" / "packaging" / "reachops.spec").read_text(encoding="utf-8")
        iss = (root / "ReachOps" / "packaging" / "ReachOps.iss").read_text(encoding="utf-8")
        build_script = (root / "tools" / "build_reachops_windows.ps1").read_text(encoding="utf-8")
        web_ui_script = (root / "tools" / "reachops_web_ui.py").read_text(encoding="utf-8")
        acceptance_script = (root / "tools" / "run_reachops_acceptance_windows.ps1").read_text(encoding="utf-8")
        acceptance_background_script = (root / "tools" / "start_reachops_acceptance_background_windows.ps1").read_text(encoding="utf-8")
        acceptance_background_status_script = (root / "tools" / "get_reachops_acceptance_background_status_windows.ps1").read_text(encoding="utf-8")
        live_acceptance_status = (root / "tools" / "reachops_live_acceptance_status.py").read_text(encoding="utf-8")
        live_environment_blocker_script = (root / "tools" / "reachops_live_environment_blocker_report.py").read_text(encoding="utf-8")
        live_readiness_windows_script = (root / "tools" / "run_reachops_live_readiness_windows.ps1").read_text(encoding="utf-8")
        live_validation_windows_script = (root / "tools" / "run_reachops_live_validation_manifest_windows.ps1").read_text(encoding="utf-8")
        live_preflight_windows_script = (root / "tools" / "run_reachops_live_preflight_windows.ps1").read_text(encoding="utf-8")
        installer_smoke_script = (root / "tools" / "run_reachops_installer_smoke_windows.ps1").read_text(encoding="utf-8")
        ui_startup_smoke_script = (root / "tools" / "run_reachops_ui_startup_smoke_windows.ps1").read_text(encoding="utf-8")
        ui_start_script = (root / "tools" / "start_reachops_ui_windows.ps1").read_text(encoding="utf-8")
        ui_start_bat = (root / "tools" / "start_growth_ui_windows.bat").read_text(encoding="utf-8")
        sync_script = (root / "tools" / "sync_reachops_to_windows_vm.sh").read_text(encoding="utf-8")
        root_requirements = (root / "requirements.txt").read_text(encoding="utf-8")
        dependency_lock = (root / "requirements.lock").read_text(encoding="utf-8")
        reachops_requirements = (root / "ReachOps" / "packaging" / "requirements-reachops.txt").read_text(encoding="utf-8")
        dependency_license_inventory = (root / "ReachOps" / "packaging" / "dependency-license-inventory.json").read_text(encoding="utf-8")
        dependency_baseline_verifier = (root / "tools" / "verify_reachops_dependency_baseline.py").read_text(encoding="utf-8")
        ci_release_baseline_audit = (root / "tools" / "reachops_ci_release_baseline_audit.py").read_text(encoding="utf-8")
        account_readiness_audit = (root / "tools" / "reachops_account_readiness_audit.py").read_text(encoding="utf-8")
        control_plane_audit = (root / "tools" / "reachops_control_plane_audit.py").read_text(encoding="utf-8")
        issue_closure_audit = (root / "tools" / "reachops_issue_closure_audit.py").read_text(encoding="utf-8")
        delivery_audit = (root / "tools" / "reachops_delivery_audit.py").read_text(encoding="utf-8")
        data_governance = (root / "tools" / "reachops_data_governance.py").read_text(encoding="utf-8")
        security_supply_chain_audit = (root / "tools" / "reachops_security_supply_chain_audit.py").read_text(encoding="utf-8")
        start_contract_audit = (root / "tools" / "reachops_start_contract_audit.py").read_text(encoding="utf-8")
        data_migrations = (root / "ReachOps" / "intelligence" / "migrations.py").read_text(encoding="utf-8")
        outcome_metrics = (root / "tools" / "reachops_outcome_metrics.py").read_text(encoding="utf-8")
        storage = (root / "ReachOps" / "intelligence" / "storage.py").read_text(encoding="utf-8")
        security_signing = (root / "ReachOps" / "security_signing.py").read_text(encoding="utf-8")
        authorization_gate = (root / "ReachOps" / "workbench" / "authorization_gate.py").read_text(encoding="utf-8")
        updater = (root / "ReachOps" / "updater.py").read_text(encoding="utf-8")
        update_manifest_writer = (root / "tools" / "write_reachops_update_manifest.py").read_text(encoding="utf-8")
        release_evidence = (root / "tools" / "reachops_release_evidence.py").read_text(encoding="utf-8")
        final_acceptance_gate_tool = (root / "tools" / "reachops_final_acceptance_gate.py").read_text(encoding="utf-8")
        goal_delivery_runner_tool = (root / "tools" / "reachops_goal_delivery_runner.py").read_text(encoding="utf-8")
        acceptance_verifier = (root / "tools" / "verify_reachops_acceptance_summary.py").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "reachops-ci.yml").read_text(encoding="utf-8")
        acceptance_inputs_template = (root / "tools" / "reachops_acceptance_inputs.example.ps1").read_text(encoding="utf-8")
        acceptance_inputs_init = (root / "tools" / "init_reachops_acceptance_inputs_windows.ps1").read_text(encoding="utf-8")
        acceptance_inputs_init_py = (root / "tools" / "init_reachops_acceptance_inputs.py").read_text(encoding="utf-8")
        live_acceptance_runbook = (root / "ReachOps" / "docs" / "REACHOPS_WINDOWS_LIVE_ACCEPTANCE_RUNBOOK.md").read_text(encoding="utf-8")
        pressure_audit_report = (root / "ReachOps" / "docs" / "REACHOPS_REAL_PRESSURE_AUDIT_ACCEPTANCE_REPORT.md").read_text(encoding="utf-8")
        handoff = (root / "HANDOFF.md").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        reachops_readme = (root / "ReachOps" / "README.md").read_text(encoding="utf-8")
        delivery_plan = (root / "ReachOps" / "docs" / "REACHOPS_DELIVERY_EXECUTION_PLAN.md").read_text(encoding="utf-8")
        operator_matrix = (root / "ReachOps" / "docs" / "REACHOPS_OPERATOR_ACCEPTANCE_MATRIX.md").read_text(encoding="utf-8")
        goal_mode_execution = (root / "ReachOps" / "docs" / "REACHOPS_GOAL_MODE_EXECUTION.md").read_text(encoding="utf-8")
        pm_delivery_baseline = (root / "ReachOps" / "docs" / "REACHOPS_PM_DELIVERY_BASELINE.md").read_text(encoding="utf-8")
        phase2_handoff = (root / "ReachOps" / "docs" / "REACHOPS_PHASE2_WINDOWS_AUTH_HANDOFF.md").read_text(encoding="utf-8")
        mac_local_mvp_acceptance = (root / "ReachOps" / "docs" / "REACHOPS_MAC_LOCAL_MVP_ACCEPTANCE.md").read_text(encoding="utf-8")
        ixbrowser_repair_acceptance = (root / "ReachOps" / "docs" / "REACHOPS_IXBROWSER_API_REPAIR_ACCEPTANCE_2026-07-13.md").read_text(encoding="utf-8")

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
        self.assertIn("requirements.lock", build_script)
        self.assertIn("tools\\verify_reachops_dependency_baseline.py", build_script)
        self.assertIn("--json", build_script)
        self.assertIn("Install ReachOps locked requirements", build_script)
        self.assertIn("Resolve-VersionInfoBuild", build_script)
        self.assertIn("$number -le 65535", build_script)
        self.assertIn("$number % 65535", build_script)
        self.assertIn("/DMyVersionInfoBuild=$VersionInfoBuild", build_script)
        self.assertIn("ReachOpsApp.py", build_script)
        self.assertIn("Assert-LastExitCode \"ReachOps PyInstaller build\"", build_script)
        self.assertIn("Find-InnoSetupCompiler", build_script)
        self.assertIn("Inno Setup 6\\ISCC.exe", build_script)
        self.assertIn("tools\\reachops_delivery_smoke.py --json", build_script)
        self.assertIn("tools\\reachops_delivery_audit.py --json", build_script)
        self.assertIn("tools\\reachops_delivery_package_check.py", build_script)
        self.assertIn("tools\\reachops_final_acceptance_gate.py", build_script)
        self.assertIn("tools\\reachops_live_acceptance_status.py", build_script)
        self.assertIn("tools\\reachops_live_environment_blocker_report.py", build_script)
        self.assertIn("tools\\reachops_repository_cleanliness_check.py", build_script)
        self.assertIn("tools\\verify_reachops_acceptance_summary.py", build_script)
        self.assertIn("Remove-PythonCacheArtifacts", build_script)
        self.assertIn('Filter "__pycache__"', build_script)
        self.assertIn('"*.pyc","*.pyo"', build_script)
        self.assertIn("write_reachops_update_manifest.py", build_script)
        self.assertIn("tools\\reachops_release_evidence.py", build_script)
        self.assertIn("Assert-LastExitCode \"ReachOps release evidence\"", build_script)
        self.assertIn("SkipInstallerSmoke", build_script)
        self.assertIn("tools\\run_reachops_installer_smoke_windows.ps1", build_script)
        self.assertIn("Assert-LastExitCode \"ReachOps installer smoke\"", build_script)
        self.assertIn("Assert-LastExitCode \"ReachOps update manifest\"", build_script)
        self.assertIn("tools\\reachops_delivery_audit.py", acceptance_script)
        self.assertIn("tools\\reachops_operator_pressure.py", acceptance_script)
        self.assertIn("tools\\reachops_goal_status_report.py", acceptance_script)
        self.assertIn("tools\\reachops_issue_closure_audit.py", acceptance_script)
        self.assertIn("tools\\reachops_delivery_package_check.py", acceptance_script)
        self.assertIn("tools\\reachops_final_acceptance_gate.py", acceptance_script)
        self.assertIn("--issue-closure-json", acceptance_script)
        self.assertIn("--allow-missing-final-gate", acceptance_script)
        self.assertIn("--allow-final-gate-convergence", acceptance_script)
        self.assertIn("ReachOps delivery package convergence evidence check", acceptance_script)
        self.assertIn("ReachOps delivery package strict final evidence check", acceptance_script)
        self.assertIn("ReachOps strict final acceptance gate after package convergence", acceptance_script)
        self.assertIn("tools\\reachops_activation_status_check.py", acceptance_script)
        self.assertIn("tools\\reachops_live_preflight.py", acceptance_script)
        self.assertIn("tools\\reachops_live_readiness.py", acceptance_script)
        self.assertIn("tools\\reachops_live_validation_manifest.py", acceptance_script)
        self.assertIn("tools\\reachops_repository_cleanliness_check.py", acceptance_script)
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
        self.assertIn("ACTIVATION_STATUS_JSON", acceptance_script)
        self.assertIn("LIVE_ACCEPTANCE_STATUS_JSON", acceptance_script)
        self.assertIn("REPOSITORY_CLEANLINESS_JSON", acceptance_script)
        self.assertIn("repository_cleanliness_payload.json", acceptance_script)
        self.assertIn("repository_cleanliness", acceptance_script)
        self.assertIn("WINDOWS_PACKAGE_PREFLIGHT_JSON", acceptance_script)
        self.assertIn("windows_package_preflight.json", acceptance_script)
        self.assertIn("windows_package_preflight", acceptance_script)
        self.assertIn("ReachOps client delivery gate", acceptance_script)
        self.assertIn("tools\\reachops_client_delivery_check.py", acceptance_script)
        self.assertIn("client_delivery.json", acceptance_script)
        self.assertIn("CLIENT_DELIVERY_JSON", acceptance_script)
        self.assertIn("client_delivery", acceptance_script)
        self.assertIn("issue_closure_payload.json", acceptance_script)
        self.assertIn("ISSUE_CLOSURE_JSON", acceptance_script)
        self.assertIn("issue_closure", acceptance_script)
        self.assertIn("Filter __pycache__", sync_script)
        self.assertIn("*.pyc,*.pyo", sync_script)
        self.assertIn("Remove-Item -Recurse -Force", sync_script)
        self.assertIn("live_acceptance_status_payload.json", acceptance_script)
        self.assertIn("live_acceptance_status", acceptance_script)
        self.assertIn("authorization_handoff_payload.json", acceptance_script)
        self.assertIn("latest_reachops_authorization_handoff.zip", acceptance_script)
        self.assertIn("latest_live_acceptance_readiness.json", acceptance_script)
        self.assertIn("latest_live_acceptance_readiness.md", acceptance_script)
        self.assertIn("readiness_report_path", acceptance_script)
        self.assertIn("readiness_json_path", acceptance_script)
        self.assertIn("tools\\reachops_authorization_handoff_bundle.py", acceptance_script)
        self.assertIn("authorization_handoff = [ordered]@", acceptance_script)
        self.assertIn("-AuthorizationHandoffJsonPath $authorizationHandoffJson", acceptance_script)
        self.assertIn("[string]$InputFile", acceptance_script)
        self.assertIn("Import-AcceptanceInputFile", acceptance_script)
        self.assertIn("--local-inputs-path", acceptance_script)
        self.assertIn("local_inputs.usable=true", acceptance_script)
        self.assertIn("ready_for_live_submit=true", acceptance_script)
        self.assertIn("verification_commands", acceptance_script)
        self.assertIn("reachops_goal_delivery_runner.py --json", live_acceptance_status)
        self.assertIn("delivery_package_check.json", acceptance_script)
        self.assertIn("final_acceptance_gate.json", acceptance_script)
        self.assertIn("FINAL_ACCEPTANCE_GATE_JSON", acceptance_script)
        self.assertIn("Add-FinalGateToAcceptanceSummary", acceptance_script)
        self.assertIn("--acceptance-summary", acceptance_script)
        self.assertIn("ReachOps delivery package check failed for final passed acceptance", acceptance_script)
        self.assertIn("ReachOps delivery package convergence evidence check", acceptance_script)
        self.assertIn("ReachOps delivery package convergence evidence check failed for final passed acceptance", acceptance_script)
        self.assertIn("ReachOps delivery package strict final evidence check", acceptance_script)
        self.assertIn("ReachOps delivery package strict final evidence check failed for final passed acceptance", acceptance_script)
        self.assertIn("ReachOps strict final acceptance gate final evidence check", acceptance_script)
        self.assertIn("ReachOps final acceptance gate failed for final passed acceptance", acceptance_script)
        self.assertIn("ReachOps strict final acceptance gate after package convergence", acceptance_script)
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
        self.assertIn("--dm-profile-url", acceptance_script)
        self.assertIn("LIVE_READINESS_JSON", acceptance_script)
        self.assertIn("LIVE_VALIDATION_MANIFEST_JSON", acceptance_script)
        self.assertIn("live_validation", acceptance_script)
        self.assertIn("live_readiness", acceptance_script)
        self.assertIn("Live readiness is blocked; still writing no-submit preflight input report", acceptance_script)
        self.assertIn("ReachOps live preflight without submit", acceptance_script)
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
        self.assertIn("ReuseExistingUiStartup", acceptance_script)
        self.assertIn("reused_existing_ui_startup_state", acceptance_script)
        self.assertIn("activation_status_payload.json", acceptance_script)
        self.assertIn("activation_status", acceptance_script)
        self.assertIn("UTF8Encoding($false)", acceptance_script)
        self.assertIn("(Get-Location).ProviderPath", acceptance_script)
        self.assertIn("while ($idx -ge 0)", acceptance_script)
        self.assertNotIn("Tee-Object", acceptance_script)
        self.assertIn("Register-ScheduledTask", acceptance_background_script)
        self.assertIn("Start-ScheduledTask", acceptance_background_script)
        self.assertIn("launch_method = \"scheduled_task\"", acceptance_background_script)
        self.assertIn("powershell.exe", acceptance_background_script)
        self.assertIn("2>", acceptance_background_script)
        self.assertIn("acceptance_background_run.json", acceptance_background_script)
        self.assertIn("acceptance_command.ps1", acceptance_background_script)
        self.assertIn("ACCEPTANCE_BACKGROUND_PID", acceptance_background_script)
        self.assertIn("run_reachops_acceptance_windows.ps1", acceptance_background_script)
        self.assertIn("[string]$InputFile", acceptance_background_script)
        self.assertIn("Import-AcceptanceInputFile", acceptance_background_script)
        self.assertIn("-InputFile", acceptance_background_script)
        self.assertIn("RunControlledLiveSubmit", acceptance_background_script)
        self.assertIn("-ReuseExistingUiStartup", acceptance_background_script)
        self.assertIn("input_file = $InputFile", acceptance_background_script)
        self.assertIn("task_name = $taskName", acceptance_background_script)
        self.assertIn("command_script_path = $commandScriptPath", acceptance_background_script)
        self.assertIn("Quote-ProcessArgument", acceptance_background_script)
        self.assertIn("$argumentLine", acceptance_background_script)
        self.assertIn("[System.IO.Path]::GetFullPath", acceptance_background_script)
        self.assertIn("[System.IO.Path]::IsPathRooted", acceptance_background_script)
        self.assertIn("verify_reachops_acceptance_summary.py", acceptance_background_status_script)
        self.assertIn("ACCEPTANCE_SUMMARY_JSON=", acceptance_background_status_script)
        self.assertIn("FINAL_ACCEPTANCE_GATE_JSON=", acceptance_background_status_script)
        self.assertIn("ISSUE_CLOSURE_JSON=", acceptance_background_status_script)
        self.assertIn("acceptance_verification", acceptance_background_status_script)
        self.assertIn("delivery_package_check_path", acceptance_background_status_script)
        self.assertIn("delivery_package_check_exists", acceptance_background_status_script)
        self.assertIn("delivery_package_check = $deliveryPackageCheck", acceptance_background_status_script)
        self.assertIn("WINDOWS_PACKAGE_PREFLIGHT_JSON=", acceptance_background_status_script)
        self.assertIn("windows_package_preflight_path", acceptance_background_status_script)
        self.assertIn("windows_package_preflight_exists", acceptance_background_status_script)
        self.assertIn("windows_package_preflight = $windowsPackagePreflight", acceptance_background_status_script)
        self.assertIn("windows_package_preflight_missing", acceptance_background_status_script)
        self.assertIn("windows_package_preflight_not_ready", acceptance_background_status_script)
        self.assertIn("issue_closure_path", acceptance_background_status_script)
        self.assertIn("issue_closure_exists", acceptance_background_status_script)
        self.assertIn("issue_closure = $issueClosure", acceptance_background_status_script)
        self.assertIn("issue_closure_ready = $issueClosureReady", acceptance_background_status_script)
        self.assertIn("issue_closure_missing", acceptance_background_status_script)
        self.assertIn("issue_closure_not_closed", acceptance_background_status_script)
        self.assertIn("$RequiredPackageReportFiles", acceptance_background_status_script)
        self.assertIn("required_package_report_files = $RequiredPackageReportFiles", acceptance_background_status_script)
        self.assertIn("missing_package_report_files = $missingPackageReportFiles", acceptance_background_status_script)
        self.assertIn("MISSING_PACKAGE_REPORT_FILES=", acceptance_background_status_script)
        self.assertIn("issue_closure_report_missing", acceptance_background_status_script)
        self.assertIn("authorization_handoff_report_missing", acceptance_background_status_script)
        self.assertIn("client_delivery_report_missing", acceptance_background_status_script)
        self.assertIn("repository_cleanliness_report_missing", acceptance_background_status_script)
        self.assertIn("final_acceptance_gate_report_missing", acceptance_background_status_script)
        self.assertIn('"repository_cleanliness"', acceptance_background_status_script)
        self.assertIn('"final_acceptance_gate"', acceptance_background_status_script)
        self.assertIn("$deliveryPackageReady", acceptance_background_status_script)
        self.assertIn("delivery_package_check_not_final_ready", acceptance_background_status_script)
        self.assertIn("final_gate_report", acceptance_background_status_script)
        self.assertIn("missing_required_checks", acceptance_background_status_script)
        self.assertIn("failed_required_checks", acceptance_background_status_script)
        self.assertIn("checks_by_name", acceptance_background_status_script)
        self.assertIn("final_acceptance_gate_path", acceptance_background_status_script)
        self.assertIn("final_acceptance_gate_exists", acceptance_background_status_script)
        self.assertIn("final_acceptance_gate = $finalAcceptanceGate", acceptance_background_status_script)
        self.assertIn("final_delivery_ready = $finalDeliveryReady", acceptance_background_status_script)
        self.assertIn("final_delivery_blockers = $finalDeliveryBlockers", acceptance_background_status_script)
        self.assertIn("verification_commands = $FinalVerificationCommands", acceptance_background_status_script)
        self.assertIn("FINAL_DELIVERY_READY=", acceptance_background_status_script)
        self.assertIn("FINAL_DELIVERY_BLOCKERS=", acceptance_background_status_script)
        self.assertIn("VERIFICATION_COMMANDS=", acceptance_background_status_script)
        self.assertIn("reachops_client_delivery_check.py --json", acceptance_background_status_script)
        self.assertIn("reachops_goal_delivery_runner.py --json", acceptance_background_status_script)
        self.assertIn("reachops_delivery_package_check.py --json", acceptance_background_status_script)
        self.assertIn("reachops_issue_closure_audit.py --json", acceptance_background_status_script)
        self.assertIn("reachops_final_acceptance_gate.py --json", acceptance_background_status_script)
        self.assertIn("final_acceptance_gate_not_ready", acceptance_background_status_script)
        self.assertIn("task_name", acceptance_background_status_script)
        self.assertIn("task_state", acceptance_background_status_script)
        self.assertIn("task_last_result", acceptance_background_status_script)
        self.assertIn("Get-ScheduledTask", acceptance_background_status_script)
        self.assertIn("Get-ScheduledTaskInfo", acceptance_background_status_script)
        self.assertIn("stdout_tail", acceptance_background_status_script)
        self.assertIn("stderr_tail", acceptance_background_status_script)
        self.assertNotIn("$pid =", acceptance_background_status_script)
        self.assertIn("$processId =", acceptance_background_status_script)
        self.assertIn("milestone3_status", live_environment_blocker_script)
        self.assertIn("background_acceptance_no_submit", live_environment_blocker_script)
        self.assertIn("ixbrowser_profile_environment", live_environment_blocker_script)
        self.assertIn("final_delivery_package", live_environment_blocker_script)
        self.assertIn("package_final_ready", live_environment_blocker_script)
        self.assertIn("artifacts_ready", live_environment_blocker_script)
        self.assertIn("manifest_ready", live_environment_blocker_script)
        self.assertIn("report_files_ready", live_environment_blocker_script)
        self.assertIn("authorization_handoff", live_environment_blocker_script)
        self.assertIn("windows_package_preflight", live_environment_blocker_script)
        self.assertIn("acceptance_verification_ready", live_environment_blocker_script)
        self.assertIn("package_final_gate_summary_ready", live_environment_blocker_script)
        self.assertIn("final_gate_summary_ready", live_environment_blocker_script)
        self.assertIn("final_gate_report", live_environment_blocker_script)
        self.assertIn("bootstrap_only", live_environment_blocker_script)
        self.assertIn("tools\\reachops_live_readiness.py", live_readiness_windows_script)
        self.assertIn("No browser will be opened", live_readiness_windows_script)
        self.assertIn("No comment/follow/dm will be submitted", live_readiness_windows_script)
        self.assertIn("LIVE_READINESS_JSON", live_readiness_windows_script)
        self.assertIn("ConfirmAuthorizedTargets", live_readiness_windows_script)
        self.assertIn("AllowPressureSubmit", live_readiness_windows_script)
        self.assertIn("--allow-pressure-submit", live_readiness_windows_script)
        self.assertIn("--limit\", \"$Limit", live_readiness_windows_script)
        self.assertIn("ReachOps live readiness blocked", live_readiness_windows_script)
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
        self.assertIn("DmProfileUrl", live_preflight_windows_script)
        self.assertIn("--dm-profile-url", live_preflight_windows_script)
        self.assertIn("ReachOps live preflight blocked or failed", live_preflight_windows_script)
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
        self.assertIn('client_surface = "local_client_console"', ui_start_script)
        self.assertIn('display_name = "ReachOps Local Client Console"', ui_start_script)
        self.assertIn('loopback_host = "127.0.0.1"', ui_start_script)
        self.assertNotIn("GrowthIntelligenceApp.py", ui_start_script)
        self.assertIn("start_reachops_ui_windows.ps1", ui_start_bat)
        self.assertIn("C:\\Users\\aofa\\ReachOps_client", ui_start_bat)
        self.assertNotIn("IntelliOps_codex_growth_ui", ui_start_bat)
        self.assertIn("start_reachops_ui_windows.ps1", ui_startup_smoke_script)
        self.assertIn("-InteractiveTask", ui_startup_smoke_script)
        self.assertIn("process_running", ui_startup_smoke_script)
        self.assertIn("client_surface_not_local_console", ui_startup_smoke_script)
        self.assertIn("loopback_host_not_local", ui_startup_smoke_script)
        self.assertIn("KeepRunning", ui_startup_smoke_script)
        self.assertIn("reachops_web_ui.py", build_script)
        self.assertIn("reachops_client_delivery_check.py", build_script)
        self.assertIn("reachops_web_panel_runtime_smoke.py", build_script)
        self.assertIn("tools\\reachops_issue_closure_audit.py", build_script)
        self.assertIn("reachops_live_submit_acceptance.py", sync_script)
        self.assertIn("reachops_web_ui.py", sync_script)
        self.assertIn("reachops_mac_web_ui.py", sync_script)
        self.assertIn("reachops_mac_self_check.py", sync_script)
        self.assertIn("reachops_client_acceptance_status.py", sync_script)
        self.assertIn("reachops_client_delivery_check.py", sync_script)
        self.assertIn("reachops_web_panel_dom_smoke.py", sync_script)
        self.assertIn("reachops_web_panel_runtime_smoke.py", sync_script)
        self.assertIn("reachops_live_readiness.py", sync_script)
        self.assertIn("reachops_activation_status_check.py", sync_script)
        self.assertIn("init_reachops_acceptance_inputs.py", sync_script)
        self.assertIn("reachops_activation_status_template.py", sync_script)
        self.assertIn("reachops_live_acceptance_status.py", sync_script)
        self.assertIn("reachops_goal_status_report.py", sync_script)
        self.assertIn("reachops_operator_pressure.py", sync_script)
        self.assertIn("reachops_action_preflight_existing_batch.py", sync_script)
        self.assertIn("reachops_real_acquisition_report.py", sync_script)
        self.assertIn("reachops_visual_collection_preflight.py", sync_script)
        self.assertIn("capture_windows_desktop_hidden.ps1", sync_script)
        self.assertIn("reachops_live_validation_manifest.py", sync_script)
        self.assertIn("reachops_live_acceptance_status.py", sync_script)
        self.assertIn("reachops_live_environment_blocker_report.py", sync_script)
        self.assertIn("reachops_ixbrowser_profile_metadata_report.py", sync_script)
        self.assertIn("run_reachops_live_validation_manifest_windows.ps1", sync_script)
        self.assertIn("run_reachops_live_readiness_windows.ps1", sync_script)
        self.assertIn("run_reachops_live_preflight_windows.ps1", sync_script)
        self.assertIn("start_reachops_ui_windows.ps1", sync_script)
        self.assertIn("run_reachops_ui_startup_smoke_windows.ps1", sync_script)
        self.assertIn("启动ReachOps本地客户端.command", sync_script)
        self.assertIn("启动ReachOps统一WebUI.command", sync_script)
        self.assertIn("执行ReachOps账号修复.command", sync_script)
        self.assertIn("run_reachops_installer_smoke_windows.ps1", sync_script)
        self.assertIn("run_reachops_acceptance_windows.ps1", sync_script)
        self.assertIn("start_reachops_acceptance_background_windows.ps1", sync_script)
        self.assertIn("get_reachops_acceptance_background_status_windows.ps1", sync_script)
        self.assertIn("verify_reachops_acceptance_summary.py", sync_script)
        self.assertIn("reachops_delivery_package_check.py", sync_script)
        self.assertIn("reachops_issue_closure_audit.py", sync_script)
        self.assertIn("reachops_final_acceptance_gate.py", sync_script)
        self.assertIn("reachops_issue_closure_audit.py --json", sync_script)
        self.assertIn("reachops_final_acceptance_gate.py --json", delivery_plan)
        self.assertIn("reachops_issue_closure_audit.py --json", web_ui_script)
        self.assertIn("final_delivery_ready=true", delivery_plan)
        self.assertIn("failed_checks=[]", delivery_plan)
        self.assertIn("reachops_final_acceptance_gate.py --json", operator_matrix)
        self.assertIn("reachops_issue_closure_audit.py --json", operator_matrix)
        self.assertIn("reachops_client_delivery_check.py --json", operator_matrix)
        self.assertIn("reachops_delivery_package_check.py --json", operator_matrix)
        self.assertIn("issue_closure_payload.json", operator_matrix)
        self.assertIn("commercial_issue_closure:closed", operator_matrix)
        self.assertIn("final_acceptance_gate.json", operator_matrix)
        self.assertIn("reachops_issue_closure_audit.py --json", goal_mode_execution)
        self.assertIn("issue_closure_payload.json", goal_mode_execution)
        self.assertIn("commercial_issue_closure:closed", goal_mode_execution)
        self.assertIn("issue_closure_payload.json", pm_delivery_baseline)
        self.assertIn("issue_closure", pm_delivery_baseline)
        self.assertIn("commercial_issue_closure:closed", pm_delivery_baseline)
        self.assertIn("reachops_issue_closure_audit.py --json", phase2_handoff)
        self.assertIn("reachops_final_acceptance_gate.py --json", phase2_handoff)
        self.assertIn("reachops_issue_closure_audit.py --json", mac_local_mvp_acceptance)
        self.assertIn("reachops_final_acceptance_gate.py --json", mac_local_mvp_acceptance)
        self.assertIn("reachops_issue_closure_audit.py --json", delivery_plan)
        self.assertIn("commercial_issue_closure:closed", delivery_plan)
        self.assertIn("reachops_final_acceptance_gate.py --json", reachops_readme)
        self.assertIn("final_delivery_ready=true", reachops_readme)
        self.assertIn("failed_checks=[]", reachops_readme)
        self.assertIn("reachops_acceptance_inputs.example.ps1", sync_script)
        self.assertIn("init_reachops_acceptance_inputs_windows.ps1", sync_script)
        self.assertIn("init_reachops_acceptance_inputs.py missing", sync_script)
        self.assertIn("init_reachops_acceptance_inputs_windows.ps1 missing", sync_script)
        self.assertIn("reachops_delivery_audit.py --json", sync_script)
        self.assertIn("reachops_operator_pressure.py --json", sync_script)
        self.assertIn("reachops_final_acceptance_gate.py --json", sync_script)
        self.assertIn("reachops_issue_closure_sync.json", sync_script)
        self.assertIn("reachops_final_acceptance_gate_sync.json", sync_script)
        self.assertIn("SYNC_ISSUE_CLOSURE_STATUS=", sync_script)
        self.assertIn("SYNC_FINAL_ACCEPTANCE_GATE_STATUS=", sync_script)
        self.assertIn("SYNC_FINAL_DELIVERY_READY=", sync_script)
        self.assertIn("reachops_web_ui.py missing", sync_script)
        self.assertIn("reachops_client_delivery_check.py missing", sync_script)
        self.assertIn("reachops_web_panel_runtime_smoke.py missing", sync_script)
        self.assertIn("ai_strategy.py", sync_script)
        self.assertIn("requirements.txt", sync_script)
        self.assertIn("startup_icon.ico", sync_script)
        self.assertIn("ReachOpsApp.py", sync_script)
        self.assertIn("C:/Users/aofa/ReachOps_client", sync_script)
        self.assertNotIn("IntelliOps_codex_growth_ui", sync_script)
        root_requirement_lines = [line.strip() for line in root_requirements.splitlines() if line.strip() and not line.strip().startswith("#")]
        reachops_requirement_lines = [line.strip() for line in reachops_requirements.splitlines() if line.strip() and not line.strip().startswith("#")]
        self.assertEqual(root_requirement_lines, ["-r requirements.lock"])
        self.assertEqual(reachops_requirement_lines, ["-r ../../requirements.lock"])
        self.assertIn("requests==", dependency_lock)
        self.assertIn("Pillow==", dependency_lock)
        self.assertIn("selenium==", dependency_lock)
        self.assertIn("ixbrowser-local-api==", dependency_lock)
        self.assertIn("pyinstaller==", dependency_lock)
        self.assertIn("reachops.dependency_license_inventory.v1", dependency_license_inventory)
        self.assertIn("commercial_review_required_for_unknown_license", dependency_license_inventory)
        self.assertIn("pyinstaller", dependency_license_inventory)
        self.assertIn("reachops.dependency_baseline.v1", dependency_baseline_verifier)
        self.assertIn("requirements_lock_line_", dependency_baseline_verifier)
        self.assertIn("dependency_license_inventory", dependency_baseline_verifier)
        self.assertIn("reachops.ci_release_baseline_audit.v1", ci_release_baseline_audit)
        self.assertIn("python -m pip check", ci_release_baseline_audit)
        self.assertIn("ten_consecutive_ci_runs_without_code_failure", ci_release_baseline_audit)
        self.assertIn("main_branch_protection_requires_pr_review", ci_release_baseline_audit)
        self.assertIn("reachops-release-evidence.json", ci_release_baseline_audit)
        self.assertIn("reachops-rollback-note.md", ci_release_baseline_audit)
        self.assertIn("indexes_final_package_report_set", ci_release_baseline_audit)
        self.assertIn("rollback_note_exposes_report_recovery_evidence", ci_release_baseline_audit)
        self.assertIn("reachops.account_readiness_audit.v1", account_readiness_audit)
        self.assertIn("passed_with_external_account_pilot_pending", account_readiness_audit)
        self.assertIn("certified_30_controlled_profiles", account_readiness_audit)
        self.assertIn("100_real_no_submit_runs_across_three_industries", account_readiness_audit)
        self.assertIn("does_not_claim_certified_30_profiles", account_readiness_audit)
        self.assertIn("does_not_claim_100_real_no_submit_runs", account_readiness_audit)
        self.assertIn("fixture_data_excluded_by_default", account_readiness_audit)
        self.assertIn("preflight_actions_do_not_submit", account_readiness_audit)
        self.assertIn("client_delivery_exposes_real_pilot_evidence_boundary", account_readiness_audit)
        self.assertIn("reachops.real_pilot_evidence_boundary.v1", account_readiness_audit)
        self.assertIn("reachops.control_plane_audit.v1", control_plane_audit)
        self.assertIn("passed_with_external_control_plane_pending", control_plane_audit)
        self.assertIn("organization_workspace_member_role_seat_service", control_plane_audit)
        self.assertIn("server_side_rbac_enforcement_and_audit", control_plane_audit)
        self.assertIn("non_tiktok_connector_contract_implementation", control_plane_audit)
        self.assertIn("web_ui_http_api_service_connector_module_split", control_plane_audit)
        self.assertIn("does_not_claim_server_side_rbac", control_plane_audit)
        self.assertIn("does_not_claim_non_tiktok_connector_ga", control_plane_audit)
        self.assertIn("reachops.issue_closure_audit.v1", issue_closure_audit)
        self.assertIn("passed_with_external_acceptance_pending", issue_closure_audit)
        self.assertIn("issues_total", issue_closure_audit)
        self.assertIn("local_contracts_passed", issue_closure_audit)
        self.assertIn("acceptance_criteria_total", issue_closure_audit)
        self.assertIn("acceptance_criteria_local_passed", issue_closure_audit)
        self.assertIn("acceptance_criteria_external_pending", issue_closure_audit)
        self.assertIn("acceptance_criteria_unclassified", issue_closure_audit)
        self.assertIn("does_not_claim_all_issues_closed", issue_closure_audit)
        self.assertIn("closure_requires_external_validation", issue_closure_audit)
        self.assertIn("issue_1_branch_protection_pr_review_checks", issue_closure_audit)
        self.assertIn("issue_3_100_real_no_submit_runs_three_industries", issue_closure_audit)
        self.assertIn("issue_6_three_pilot_customers_attribution_before_ga", issue_closure_audit)
        self.assertIn("issue_7_server_side_roles_permissions_audited", issue_closure_audit)
        self.assertIn("[P0] Enforce CI, PR review, and deterministic release baseline", issue_closure_audit)
        self.assertIn("[P0] Freeze the /api/start contract and restore a zero-failure test baseline", issue_closure_audit)
        self.assertIn("[P0] Certify a real account-readiness pool and no-submit evidence pack", issue_closure_audit)
        self.assertIn("[P0] Harden licensing, entitlement, and the update supply chain", issue_closure_audit)
        self.assertIn("[P0] Add versioned migrations, backup/restore, retention, and privacy controls", issue_closure_audit)
        self.assertIn("[P0] Instrument WAQO and the full lead-to-revenue outcome funnel", issue_closure_audit)
        self.assertIn("[P1] Build the commercial control plane and decouple channel connectors", issue_closure_audit)
        self.assertIn("reachops.data_governance.v1", data_governance)
        self.assertIn("backup_and_restore_verify", data_governance)
        self.assertIn("reachops.support_bundle_manifest.v1", data_governance)
        self.assertIn("build_support_bundle_manifest", data_governance)
        self.assertIn("SUPPORT_BUNDLE_EXCLUDE_PATTERNS", data_governance)
        self.assertIn("RETENTION_CLASSES", data_governance)
        self.assertIn("DATA_CATALOG", data_governance)
        self.assertIn("inspect_migration_status", data_governance)
        self.assertIn("verify_privacy_operation_audit", data_governance)
        self.assertIn("reachops.privacy_operations.v1", data_governance)
        self.assertIn("reachops.recovery_objectives.v1", data_governance)
        self.assertIn("corruption_drill_required", data_governance)
        self.assertIn("--verify-privacy-ops", data_governance)
        self.assertIn("versioned_forward_migrations_with_documented_rollback", data_governance)
        self.assertIn("SCHEMA_MIGRATION_TABLE", data_governance)
        self.assertIn("dry_run_manifest_passed", delivery_audit)
        self.assertIn("activation_status_included", delivery_audit)
        self.assertIn("raw_database_included", delivery_audit)
        self.assertIn("evidence_image_included", delivery_audit)
        self.assertIn("reachops.security_supply_chain_audit.v1", security_supply_chain_audit)
        self.assertIn("reachops.entitlement_security_matrix.v1", security_supply_chain_audit)
        self.assertIn("reachops.update_supply_chain_matrix.v1", security_supply_chain_audit)
        self.assertIn("REVOCATION_SLA_HOURS", security_supply_chain_audit)
        self.assertIn("LIVE_SUBMIT_ENTITLEMENT_REPLAYED", security_supply_chain_audit)
        self.assertIn("downgrade_without_rollback_blocked", security_supply_chain_audit)
        self.assertIn("missing_evidence_contract_rejected", security_supply_chain_audit)
        self.assertIn("incomplete_evidence_contract_rejected", security_supply_chain_audit)
        self.assertIn("evidence.required_report_files", security_supply_chain_audit)
        self.assertIn("reachops.start_contract_audit.v1", start_contract_audit)
        self.assertIn("reachops.api_start_contract.v1", start_contract_audit)
        self.assertIn("profile_group_list_unavailable", start_contract_audit)
        self.assertIn("profile_group_counts_incomplete", start_contract_audit)
        self.assertIn("account_repair_required", start_contract_audit)
        self.assertIn("LIVE_SUBMIT_NOT_AUTHORIZED", start_contract_audit)
        self.assertIn("already_running", start_contract_audit)
        self.assertIn("SchemaMigration", data_migrations)
        self.assertIn("20260714_0001_data_privacy_audit", data_migrations)
        self.assertIn("20260714_0002_lead_outcomes", data_migrations)
        self.assertIn("lead_outcomes", data_migrations)
        self.assertIn("rollback_policy", data_migrations)
        self.assertIn("apply_schema_migrations", storage)
        self.assertIn("reachops.outcome_metrics.v1", outcome_metrics)
        self.assertIn("reachops.waqo_definition.v1", outcome_metrics)
        self.assertIn("Weekly Accepted Qualified Opportunities", outcome_metrics)
        self.assertIn("fixture_data_excluded_by_default", outcome_metrics)
        self.assertIn("lead-to-revenue", outcome_metrics)
        self.assertIn("SIGNATURE_ALGORITHM", security_signing)
        self.assertIn("canonical_payload", security_signing)
        self.assertIn("sign_payload", security_signing)
        self.assertIn("verify_signed_payload", security_signing)
        self.assertIn("entitlement_signature", authorization_gate)
        self.assertIn("LIVE_SUBMIT_ENTITLEMENT_SIGNATURE_INVALID", authorization_gate)
        self.assertIn("LIVE_SUBMIT_ENTITLEMENT_REVOKED", authorization_gate)
        self.assertIn("LIVE_SUBMIT_OFFLINE_GRACE_EXPIRED", authorization_gate)
        self.assertIn("LIVE_SUBMIT_DEVICE_LIMIT_EXCEEDED", authorization_gate)
        self.assertIn("LIVE_SUBMIT_FEATURE_DISABLED", authorization_gate)
        self.assertIn("packaged runtime requires a valid signed entitlement", authorization_gate)
        self.assertIn("require_signature = True", updater)
        self.assertIn("manifest_signature", updater)
        self.assertIn("manifest signature invalid", updater)
        self.assertIn("manifest channel mismatch", updater)
        self.assertIn("manifest installer.size_bytes is required", updater)
        self.assertIn("rollback_policy", updater)
        self.assertIn("manifest evidence contract is required", updater)
        self.assertIn("manifest evidence.required_report_files missing", updater)
        self.assertIn("rollback_available", updater)
        self.assertIn("sign_payload", update_manifest_writer)
        self.assertIn("manifest_signature", update_manifest_writer)
        self.assertIn("rollback_policy", update_manifest_writer)
        self.assertIn("reachops.update_manifest_evidence.v1", update_manifest_writer)
        self.assertIn("REQUIRED_FINAL_REPORT_FILES", update_manifest_writer)
        self.assertIn("--signing-key-id", update_manifest_writer)
        self.assertIn("--signing-key", update_manifest_writer)
        self.assertIn("reachops.release_evidence.v1", release_evidence)
        self.assertIn("reachops-release-evidence.json", release_evidence)
        self.assertIn("reachops-rollback-note.md", release_evidence)
        self.assertIn("check_delivery_package", release_evidence)
        self.assertIn("build_dependency_report", release_evidence)
        self.assertIn("issue_closure_payload.json", release_evidence)
        self.assertIn("authorization_handoff_readiness_report", release_evidence)
        self.assertIn("authorization_handoff_readiness_json", release_evidence)
        self.assertIn("missing_package_report_files", release_evidence)
        self.assertIn("reachops_issue_closure_audit.py --json", release_evidence)
        self.assertIn('"issue_closure"', final_acceptance_gate_tool)
        self.assertIn('"authorization_handoff"', final_acceptance_gate_tool)
        self.assertIn("authorization_handoff_readiness_report_missing", acceptance_verifier)
        self.assertIn("authorization_handoff_readiness_json_missing", acceptance_verifier)
        self.assertIn("readiness_report_inside_summary_dir", acceptance_verifier)
        self.assertIn("readiness_json_inside_summary_dir", acceptance_verifier)
        self.assertIn("issue_closure_payload", goal_delivery_runner_tool)
        self.assertIn("cache-dependency-path: requirements.lock", workflow)
        self.assertIn("tools/verify_reachops_dependency_baseline.py --json", workflow)
        self.assertIn("selenium.webdriver.chrome.webdriver", spec)
        self.assertIn("selenium.webdriver.chrome.service", spec)
        self.assertNotIn("opencv-python", reachops_requirements)
        self.assertIn("$RunControlledLiveSubmit = $false", acceptance_inputs_template)
        self.assertIn("run_reachops_live_readiness_windows.ps1", acceptance_inputs_template)
        self.assertIn("run_reachops_live_preflight_windows.ps1", acceptance_inputs_template)
        self.assertIn("-DmProfileUrl $DmProfileUrl", acceptance_inputs_template)
        self.assertIn("run_reachops_acceptance_windows.ps1", acceptance_inputs_template)
        self.assertIn("$ConfirmAuthorizedTargets = $false", acceptance_inputs_template)
        self.assertIn("ConfirmAuthorizedTargets must be `$true", acceptance_inputs_template)
        self.assertIn("Set `$RunControlledLiveSubmit = `$true", acceptance_inputs_template)
        self.assertIn("placeholder value", acceptance_inputs_template)
        self.assertIn("reachops_activation_status_check.py", acceptance_inputs_template)
        self.assertIn("reachops_live_acceptance_status.py", acceptance_inputs_template)
        self.assertIn("--confirm-authorized-targets", acceptance_inputs_template)
        self.assertIn("Activation status check blocked", acceptance_inputs_template)
        self.assertIn("ActivationStatusPath points to a template file", acceptance_inputs_template)
        self.assertIn("template_only=true", acceptance_inputs_template)
        self.assertIn("reachops_acceptance_inputs.local.ps1", acceptance_inputs_init)
        self.assertIn("reachops_acceptance_inputs.example.ps1", acceptance_inputs_init)
        self.assertIn("[switch]$Json", acceptance_inputs_init)
        self.assertIn("ConvertTo-Json -Depth 12", acceptance_inputs_init)
        self.assertIn("local_inputs = $readiness.local_inputs", acceptance_inputs_init)
        self.assertIn("report_path = $readiness.report_path", acceptance_inputs_init)
        self.assertIn("json_report_path = $readiness.json_report_path", acceptance_inputs_init)
        self.assertIn("operator_commands = $readiness.operator_commands", acceptance_inputs_init)
        self.assertIn("verification_commands", acceptance_inputs_init)
        self.assertIn("-not ($Force -or $UpdateExisting)", acceptance_inputs_init)
        self.assertIn("-UpdateExisting to set only supplied fields", acceptance_inputs_init)
        self.assertIn("python tools\\reachops_live_acceptance_status.py --write-report --json-report-path --json", acceptance_inputs_init)
        self.assertIn("python tools\\reachops_goal_delivery_runner.py --json", acceptance_inputs_init)
        self.assertIn("python tools\\reachops_issue_closure_audit.py --json", acceptance_inputs_init)
        self.assertIn("Create the local ReachOps live-acceptance input file", acceptance_inputs_init_py)
        self.assertIn("--confirm-authorized-targets", acceptance_inputs_init_py)
        self.assertIn("--update-existing", acceptance_inputs_init_py)
        self.assertIn("normalize_cli_value", acceptance_inputs_init_py)
        self.assertIn("pattern.sub(lambda _match: replacement", acceptance_inputs_init_py)
        self.assertIn("reachops_goal_delivery_runner.py --json", acceptance_inputs_init_py)
        self.assertIn("reachops_issue_closure_audit.py --json", acceptance_inputs_init_py)
        self.assertIn("reachops_account_readiness_audit.py --json", readme)
        self.assertIn("30 个受控真实账号", readme)
        self.assertIn("100 次真实 no-submit 试点", readme)
        self.assertIn("reachops_control_plane_audit.py --json", readme)
        self.assertIn("server-side RBAC", readme)
        self.assertIn("非 TikTok connector", readme)
        self.assertIn("reachops_issue_closure_audit.py --json", readme)
        self.assertIn("Issues #1-#7", readme)
        self.assertIn("closure_requires_external_validation", readme)
        self.assertIn("commercial_issue_closure", readme)
        self.assertIn("acceptance_criteria_external_pending=0", readme)
        self.assertIn("init_reachops_acceptance_inputs.py --json", readme)
        self.assertIn("init_reachops_acceptance_inputs_windows.ps1", readme)
        self.assertIn("-InputFile .\\tools\\reachops_acceptance_inputs.local.ps1", readme)
        self.assertIn("init_reachops_acceptance_inputs_windows.ps1", live_acceptance_runbook)
        self.assertIn("-InputFile .\\tools\\reachops_acceptance_inputs.local.ps1", live_acceptance_runbook)
        self.assertIn("tools\\run_reachops_live_preflight_windows.ps1", live_acceptance_runbook)
        self.assertIn("tools\\reachops_activation_status_check.py", live_acceptance_runbook)
        self.assertIn("tools\\reachops_activation_status_template.py", live_acceptance_runbook)
        self.assertIn("tools\\reachops_live_acceptance_status.py", live_acceptance_runbook)
        self.assertIn("tools\\reachops_client_delivery_check.py --json", live_acceptance_runbook)
        self.assertIn("tools\\reachops_final_acceptance_gate.py --json", live_acceptance_runbook)
        self.assertIn("failed_checks=[]", live_acceptance_runbook)
        self.assertIn("acceptance_ready=true", live_acceptance_runbook)
        self.assertIn("readiness=pass", live_acceptance_runbook)
        self.assertIn("latest_delivery_check.json", live_acceptance_runbook)
        self.assertIn("delivery_check_path", live_acceptance_runbook)
        self.assertIn("platform_selenium", live_acceptance_runbook)
        self.assertIn("template_only", live_acceptance_runbook)
        self.assertIn("reachops_activation_status_template.py", readme)
        self.assertIn("entitlement_signature", readme)
        self.assertIn("离线宽限", readme)
        self.assertIn("reachops_ci_release_baseline_audit.py --json", readme)
        self.assertIn("manifest_signature", reachops_readme)
        self.assertIn("rollback_policy.allow_downgrade=true", reachops_readme)
        self.assertIn("reachops.update_manifest_evidence.v1", reachops_readme)
        self.assertIn("entitlement_signature", reachops_readme)
        self.assertIn("reachops_security_supply_chain_audit.py --json", reachops_readme)
        self.assertIn("reachops_start_contract_audit.py --json", reachops_readme)
        self.assertIn("replay", reachops_readme)
        self.assertIn("installer hash/size", reachops_readme)
        self.assertIn("schema_migrations", reachops_readme)
        self.assertIn("data_privacy_audit", reachops_readme)
        self.assertIn("reachops_data_governance.py --create-missing-db --verify-backup --verify-privacy-ops --json", reachops_readme)
        self.assertIn("RPO/RTO", reachops_readme)
        self.assertIn("corruption drill", reachops_readme)
        self.assertIn("WAQO", reachops_readme)
        self.assertIn("reachops_outcome_metrics.py --create-missing-db --json", reachops_readme)
        self.assertIn("fixture", reachops_readme)
        self.assertIn("dry_run", reachops_readme)
        self.assertIn("effective_pending_external_validation=3", readme)
        self.assertIn("客户端交付验收门禁", readme)
        self.assertIn("reachops_client_delivery_check.py --json", readme)
        self.assertIn("reachops_issue_closure_audit.py --json", readme)
        self.assertIn("reachops_final_acceptance_gate.py --json", readme)
        self.assertIn("status=passed", readme)
        self.assertIn("final_delivery_ready=true", readme)
        self.assertIn("report_files.authorization_handoff", readme)
        self.assertIn("report_files.client_delivery", readme)
        self.assertIn("delivery_check_path", readme)
        self.assertIn("latest_delivery_check.json", readme)
        self.assertIn("--allow-missing-final-gate", readme)
        self.assertIn("bootstrap_only=true", readme)
        self.assertIn("status=blocked_by_environment", readme)
        self.assertIn('failed_checks=["acceptance:ready"]', readme)
        self.assertIn("运营主入口是网页端统一控制台", readme)
        self.assertIn("/api/start", readme)
        self.assertIn("ixBrowser 本地 API", readme)
        self.assertIn("-TargetProfileUrl $FollowProfileUrl", live_acceptance_runbook)
        self.assertIn("-DmProfileUrl $DmProfileUrl", live_acceptance_runbook)
        self.assertIn("goal_status_report.json", live_acceptance_runbook)
        self.assertIn("delivery_audit_payload.json", live_acceptance_runbook)
        self.assertIn("operator_pressure_payload.json", live_acceptance_runbook)
        self.assertIn("activation_status_payload.json", live_acceptance_runbook)
        self.assertIn("authorization_handoff_payload.json", live_acceptance_runbook)
        self.assertIn("latest_reachops_authorization_handoff.zip", live_acceptance_runbook)
        self.assertIn("issue_closure_payload.json", live_acceptance_runbook)
        self.assertIn("live_readiness_payload.json", live_acceptance_runbook)
        self.assertIn("live_preflight_payload.json", live_acceptance_runbook)
        self.assertIn("live_submit_payload.json", live_acceptance_runbook)
        self.assertIn("final_acceptance_gate.json", live_acceptance_runbook)
        self.assertIn("final_delivery_blockers", live_acceptance_runbook)
        self.assertIn("bootstrap_only=true", live_acceptance_runbook)
        self.assertIn("artifacts", live_acceptance_runbook)
        self.assertIn("report_files", live_acceptance_runbook)
        self.assertIn("authorization_handoff", live_acceptance_runbook)
        self.assertIn("client_delivery", live_acceptance_runbook)
        self.assertIn("report_files.authorization_handoff", operator_matrix)
        self.assertIn("report_files.client_delivery", operator_matrix)
        self.assertIn("authorization_handoff_payload.json", pm_delivery_baseline)
        self.assertIn("latest_reachops_authorization_handoff.zip", pm_delivery_baseline)
        self.assertIn("client_delivery", pm_delivery_baseline)
        self.assertIn("latest_delivery_check.json", pressure_audit_report)
        self.assertIn("target_required", pressure_audit_report)
        self.assertIn("write_delivery_check()", pressure_audit_report)
        self.assertIn("--allow-missing-final-gate", pressure_audit_report)
        self.assertIn("bootstrap_only=true", pressure_audit_report)
        self.assertIn("summary_exists", pressure_audit_report)
        self.assertIn("package_check_exists", pressure_audit_report)
        self.assertIn("package_final_delivery_ready", pressure_audit_report)
        self.assertIn("package_bootstrap_only", pressure_audit_report)
        self.assertIn("final_delivery_package", pressure_audit_report)
        self.assertIn("final_acceptance_gate_exists", pressure_audit_report)
        self.assertIn("final_delivery_blockers", pressure_audit_report)
        self.assertIn("delivery_package_check_not_final_ready", pressure_audit_report)
        self.assertIn("SYNC_FINAL_ACCEPTANCE_GATE_STATUS", pressure_audit_report)
        self.assertIn("SYNC_ISSUE_CLOSURE_STATUS", pressure_audit_report)
        self.assertIn("verification_commands", pressure_audit_report)
        self.assertIn("最终复核命令", pressure_audit_report)
        self.assertIn("VERIFICATION_COMMANDS", pressure_audit_report)
        self.assertIn("python tools\\reachops_client_delivery_check.py --json", pressure_audit_report)
        self.assertIn("python tools\\reachops_delivery_package_check.py --json", pressure_audit_report)
        self.assertIn("python tools\\reachops_issue_closure_audit.py --json", pressure_audit_report)
        self.assertIn("python tools\\reachops_final_acceptance_gate.py --json", pressure_audit_report)
        self.assertIn("client_delivery:final_ready", pressure_audit_report)
        self.assertIn("delivery_package:passed", pressure_audit_report)
        self.assertIn("report_files", pressure_audit_report)
        self.assertIn("authorization_handoff", pressure_audit_report)
        self.assertIn("missing_package_report_files", pressure_audit_report)
        self.assertIn("MISSING_PACKAGE_REPORT_FILES", pressure_audit_report)
        self.assertIn("<report>_report_missing", pressure_audit_report)
        self.assertIn("missing_package_report_files", handoff)
        self.assertIn("MISSING_PACKAGE_REPORT_FILES", handoff)
        self.assertIn("<report>_report_missing", handoff)
        self.assertIn("最终交付文档合同", pressure_audit_report)
        self.assertIn("acceptance summary", pressure_audit_report)
        self.assertIn("v0.4.0-mvp", handoff)
        self.assertIn("20260626_133256", handoff)
        self.assertIn("live_preflight_environment_validation", handoff)
        self.assertIn("operator architecture is web-first", handoff)
        self.assertIn("IxBrowserLocalAdapter", handoff)
        self.assertIn("effective_pending_external_validation=3", handoff)
        self.assertIn("evidence://", readme)
        self.assertIn("不能用 `evidence://...` 作为真实提交成功证据", readme)
        self.assertIn("evidence://...", operator_matrix)
        self.assertIn("comment_visible_confirmed=true", operator_matrix)
        self.assertIn("evidence://...", live_acceptance_runbook)
        self.assertIn("not valid evidence for real live-submit success", live_acceptance_runbook)
        self.assertIn("evidence://...", pressure_audit_report)
        self.assertIn("不能作为真实提交成功证据", pressure_audit_report)
        self.assertIn("final_acceptance_gate.json", handoff)
        self.assertIn("issue_closure_payload.json", handoff)
        self.assertIn("commercial_issue_closure:closed", handoff)
        self.assertIn('missing_artifacts=["acceptance_summary"]', handoff)
        self.assertNotIn("exe_missing", handoff)
        self.assertNotIn("installer_missing", handoff)
        self.assertNotIn("manifest_missing", handoff)
        self.assertIn("latest_delivery_check.json", handoff)
        self.assertIn("--allow-missing-final-gate", handoff)
        self.assertIn("bootstrap_only=true", handoff)
        self.assertIn("final_delivery_blockers", handoff)
        self.assertIn("delivery_package_check_not_final_ready", handoff)
        self.assertIn("final_delivery_package", handoff)
        self.assertIn("SYNC_FINAL_ACCEPTANCE_GATE_STATUS", handoff)
        self.assertIn("SYNC_ISSUE_CLOSURE_STATUS", handoff)
        self.assertIn("verification_commands", handoff)
        self.assertIn("27273", handoff)
        self.assertIn("reachops_acceptance_inputs.local.ps1", handoff)
        self.assertIn("LOGIN_REQUIRED", handoff)
        self.assertIn("登录/注册弹窗", readme)
        self.assertIn("Login/signup dialogs", delivery_plan)
        self.assertIn("acceptance_summary_missing", readme)
        self.assertIn("issue_closure_payload.json", readme)
        self.assertIn("commercial_issue_closure:closed", ixbrowser_repair_acceptance)
        self.assertIn("Issues #1-#7 已完成商业 closure 验收", ixbrowser_repair_acceptance)
        self.assertIn("reachops_issue_closure_audit.py --json", ixbrowser_repair_acceptance)

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

    def test_login_dialog_blocks_even_when_page_has_entities(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            driver = LoginDialogDriver()
            driver.current_url = "https://www.tiktok.com/@creator"

            self.assertEqual(service.router._detect_page_state(driver), "LOGIN_REQUIRED")

    def test_tiktok_account_setup_modal_blocks_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            driver = FakeDriver()
            driver.current_url = "https://www.tiktok.com/"
            driver.script_results = [
                {
                    "url": driver.current_url,
                    "text": "how face or voice data is used important things to know got it",
                    "title": "TikTok - Make Your Day",
                    "videoLinks": 0,
                    "profileLinks": 0,
                    "loginDialog": False,
                    "exactLoginButton": False,
                    "forcedLoginText": False,
                    "accountSetupGate": True,
                    "loginPage": False,
                    "captcha": False,
                    "proxy": False,
                }
            ]

            self.assertEqual(service.router._detect_page_state(driver), "LOGIN_REQUIRED")

    def test_ordinary_popup_with_entities_does_not_block_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            driver = FakeDriver()
            driver.current_url = "https://www.tiktok.com/@creator"
            driver.script_results = [
                {
                    "url": driver.current_url,
                    "text": "creator video grid new feature notice log in later",
                    "title": "Creator | TikTok",
                    "videoLinks": 8,
                    "profileLinks": 4,
                    "loginDialog": False,
                    "exactLoginButton": True,
                    "forcedLoginText": False,
                    "loginPage": False,
                    "captcha": False,
                    "proxy": False,
                }
            ]

            self.assertEqual(service.router._detect_page_state(driver), "")

    def test_collection_stops_when_login_dialog_detected_after_profile_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = LoginDialogDriver()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: driver,
                collectors={
                    "profile": FailingCollector(),
                    "video": FailingCollector(),
                    "comment": FailingCollector(),
                    "search": FailingCollector(),
                },
            )
            service.router.profile_group_manager = FakeProfileGroupManager()
            service.router._wait_for_page = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "logged-out-profile", "group_name": "BR"}],
                GrowthTaskConfig(test_mode=False, task_delay_min_seconds=0, task_delay_max_seconds=0),
            )
            tasks = service.storage.list_collection_tasks(limit=10)

            self.assertEqual(result.processed_sources, 0)
            self.assertEqual(result.errors.get("LOGIN_REQUIRED"), 1)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["status"], "failed")
            self.assertEqual(tasks[0]["error_code"], "LOGIN_REQUIRED")
            self.assertEqual(service.router.profile_group_manager.moves, [("logged-out-profile", "LOGIN_REQUIRED")])
            self.assertEqual(service.storage.list_candidates(), [])

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

    def test_real_mode_reports_comment_user_empty_when_content_was_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": EmptyCommentCollector(),
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@empty_comments"}],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    retry_empty_result_with_next_profile=True,
                ),
            )
            tasks = service.storage.list_collection_tasks(limit=10)

            self.assertEqual(result.processed_sources, 0)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["error_code"], "COMMENT_USERS_EMPTY_RETRY")
            self.assertIn("content discovered", tasks[0]["error_message"])

    def test_empty_result_failures_put_single_profile_into_runtime_cooldown(self):
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
                [
                    {"type": "creator_url", "value": "https://www.tiktok.com/@empty_one"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@empty_two"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@empty_three"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@empty_four"},
                ],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    retry_empty_result_with_next_profile=True,
                    failure_cooldown_threshold=2,
                ),
            )
            tasks = service.storage.list_collection_tasks(limit=10)

            self.assertEqual(result.processed_sources, 0)
            self.assertEqual(len(tasks), 2)
            self.assertEqual({row["error_code"] for row in tasks}, {"EMPTY_RESULT_RETRY"})
            self.assertGreaterEqual(service.router.profile_failures.get("p1", 0), 2)

    def test_collection_account_queue_rotates_after_profile_source_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.router._wait_for_page = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_one"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_two"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_three"},
                ],
                [
                    {"profile_id": "p1", "group_name": "US"},
                    {"profile_id": "p2", "group_name": "US"},
                    {"profile_id": "p3", "group_name": "US"},
                ],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    account_queue_enabled=True,
                    max_sources_per_profile=1,
                    requested_concurrency=2,
                ),
            )

            tasks = service.storage.list_collection_tasks(limit=10)
            with service.storage.connect() as conn:
                queue_events = [
                    (row["event"], json.loads(row["payload"] or "{}"))
                    for row in conn.execute(
                        """
                        SELECT event, payload
                        FROM growth_events
                        WHERE event LIKE 'profile_queue_%'
                        ORDER BY rowid ASC
                        """
                    ).fetchall()
                ]

            self.assertEqual(result.processed_sources, 3)
            self.assertEqual({row["profile_id"] for row in tasks}, {"p1", "p2", "p3"})
            self.assertEqual(len(tasks), 3)
            quota_profiles = [
                payload["profile_id"]
                for event, payload in queue_events
                if event == "profile_queue_quota_reached"
            ]
            self.assertEqual(quota_profiles, ["p1", "p2", "p3"])

    def test_collection_reuses_profile_browser_session_across_sources_until_batch_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            opened = []

            def browser_factory(profile_id):
                driver = FakeDriver()
                opened.append((profile_id, driver))
                return driver

            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=browser_factory,
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": StaticCommentCollector(),
                    "search": object(),
                },
            )
            service.router._run_datasource = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_one"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_two"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_three"},
                ],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    account_queue_enabled=True,
                    max_sources_per_profile=100,
                    retry_empty_result_with_next_profile=False,
                ),
            )

            with service.storage.connect() as conn:
                events = [
                    row["event"]
                    for row in conn.execute(
                        """
                        SELECT event
                        FROM growth_events
                        WHERE event LIKE 'profile_session_%'
                        ORDER BY rowid ASC
                        """
                    ).fetchall()
                ]

            self.assertEqual(result.processed_sources, 3)
            self.assertEqual([profile_id for profile_id, _driver in opened], ["p1"])
            self.assertTrue(opened[0][1].quit_called)
            self.assertEqual(events.count("profile_session_retained"), 1)
            self.assertEqual(events.count("profile_session_reused"), 2)
            self.assertEqual(events.count("profile_session_closed"), 1)

    def test_collection_fills_profile_source_quota_before_switching_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.router._run_datasource = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_one"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_two"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_three"},
                ],
                [{"profile_id": "p1", "group_name": "US"}, {"profile_id": "p2", "group_name": "US"}],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    account_queue_enabled=True,
                    max_sources_per_profile=2,
                    retry_empty_result_with_next_profile=False,
                ),
            )

            with service.storage.connect() as conn:
                tasks = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT profile_id
                        FROM collection_tasks
                        ORDER BY rowid ASC
                        """
                    ).fetchall()
                ]
            self.assertEqual(result.processed_sources, 3)
            self.assertEqual([row["profile_id"] for row in tasks], ["p1", "p1", "p2"])

    def test_open_browser_fallback_respects_profile_source_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            opened = []

            def open_browser(profile_id, source_id):
                opened.append(profile_id)
                return FakeDriver()

            service.router._open_browser = open_browser
            browser, profile = service.router._open_browser_with_fallback(
                [{"profile_id": "p1", "group_name": "US"}, {"profile_id": "p2", "group_name": "US"}],
                0,
                GrowthTaskConfig(
                    account_queue_enabled=True,
                    max_sources_per_profile=100,
                ),
                "source-1",
                profile_usage={"p1": 100, "p2": 0},
            )

        self.assertIsNotNone(browser)
        self.assertEqual(profile["profile_id"], "p2")
        self.assertEqual(opened, ["p2"])

    def test_collection_dedupes_repeated_sources_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.router._run_datasource = lambda *_args, **_kwargs: True

            result = service.run_collection(
                [
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_one?utm_source=a"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_one?utm_source=b"},
                    {"type": "creator_url", "value": "https://www.tiktok.com/@creator_two"},
                ],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                    account_queue_enabled=True,
                    max_sources_per_profile=100,
                    retry_empty_result_with_next_profile=False,
                ),
            )

            tasks = service.storage.list_collection_tasks(limit=10)
            with service.storage.connect() as conn:
                event_payload = conn.execute(
                    """
                    SELECT payload
                    FROM growth_events
                    WHERE event='collection_sources_deduped'
                    ORDER BY rowid DESC
                    LIMIT 1
                    """
                ).fetchone()

            self.assertEqual(result.processed_sources, 2)
            self.assertEqual(len(tasks), 2)
            self.assertIsNotNone(event_payload)
            payload = json.loads(event_payload["payload"])
            self.assertEqual(payload["original_sources"], 3)
            self.assertEqual(payload["deduped_sources"], 2)
            self.assertEqual(payload["skipped_duplicates"], 1)

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

    def test_collection_reuses_precreated_pending_batch(self):
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
            campaign = service.create_campaign_plan("anti aging serum")["campaign"]
            precreated = service.storage.create_collection_batch(
                1,
                profile_group="US",
                campaign_id=campaign["id"],
                initial_status="pending",
            )

            result = service.run_collection(
                [{"type": "keyword", "value": "anti aging serum"}],
                [{"profile_id": "p1", "group_name": "US"}],
                GrowthTaskConfig(
                    campaign_id=campaign["id"],
                    active_batch_id=precreated.id,
                    test_mode=False,
                    task_delay_min_seconds=0,
                    task_delay_max_seconds=0,
                ),
            )
            batches = service.storage.list_collection_batches(campaign_id=campaign["id"])
            tasks = [
                row
                for row in service.storage.list_collection_tasks(limit=10)
                if row["batch_id"] == precreated.id
            ]

            self.assertEqual(result.processed_sources, 1)
            self.assertEqual([row["id"] for row in batches], [precreated.id])
            self.assertEqual(batches[0]["status"], "completed")
            self.assertEqual(tasks[0]["batch_id"], precreated.id)
            self.assertEqual(tasks[0]["status"], "completed")

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

    def test_comment_scan_records_url_mismatch_even_when_collector_returns_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": EmptyMismatchedUrlCommentCollector(),
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
        self.assertIn("URL_MISMATCH_DISCARDED", events[0]["payload"])

    def test_direct_content_url_skips_creator_fallback_after_url_mismatch_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": EmptyMismatchedUrlCommentCollector(),
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True
            datasource = type(
                "DataSourceObj",
                (),
                {"id": "as_direct", "type": "content_url", "value": "https://www.tiktok.com/@creator/video/123"},
            )()

            ok = service.router._run_content_url(
                datasource,
                FakeDriver(),
                GrowthTaskConfig(test_mode=True, comment_retry_attempts=1),
                "p1",
            )
            with service.storage.connect() as conn:
                events = [row["event"] for row in conn.execute("SELECT event FROM growth_events ORDER BY rowid")]

        self.assertFalse(ok)
        self.assertIn("content_url_creator_fallback_skipped", events)
        self.assertNotIn("content_url_creator_fallback_started", events)

    def test_comment_scan_accepts_same_creator_other_video_comments_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = SameCreatorOtherVideoCommentCollector()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": collector,
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True
            driver = FakeDriver()
            driver.get("https://www.tiktok.com/@creator/video/123")

            comments, evidence = service.router._collect_comments_with_retry(
                driver,
                {
                    "id": "ct_target",
                    "video_id": "123",
                    "video_url": "https://www.tiktok.com/@creator/video/123",
                },
                GrowthTaskConfig(test_mode=True, comment_retry_attempts=3),
                "comment_scan",
            )
            with service.storage.connect() as conn:
                event = conn.execute(
                    "SELECT payload FROM growth_events WHERE event='comment_scan_same_creator_fallback_accepted'"
                ).fetchone()

        self.assertEqual(len(comments), 1)
        self.assertEqual(evidence.final_url, "https://www.tiktok.com/@creator/video/999")
        self.assertEqual(collector.calls, 1)
        self.assertIsNotNone(event)
        self.assertIn('"comment_count": 1', event["payload"])

    def test_comment_scan_retries_after_same_creator_other_video_drift_when_fallback_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = SameCreatorOtherVideoCommentCollector()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": collector,
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True
            driver = FakeDriver()
            driver.get("https://www.tiktok.com/@creator/video/123")

            comments, evidence = service.router._collect_comments_with_retry(
                driver,
                {
                    "id": "ct_target",
                    "video_id": "123",
                    "video_url": "https://www.tiktok.com/@creator/video/123",
                },
                GrowthTaskConfig(test_mode=True, comment_retry_attempts=3, accept_same_creator_video_comments=False),
                "comment_scan",
            )
            with service.storage.connect() as conn:
                event = conn.execute(
                    "SELECT payload FROM growth_events WHERE event='comment_scan_followed_same_creator_video'"
                ).fetchone()

        self.assertEqual(len(comments), 1)
        self.assertEqual(evidence.final_url, "https://www.tiktok.com/@creator/video/123")
        self.assertEqual(collector.calls, 2)
        self.assertIsNotNone(event)
        self.assertIn('"comment_count": 1', event["payload"])

    def test_comment_scan_recovers_after_recommended_video_url_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = RecoveringUrlCommentCollector()
            service = GrowthIntelligenceService(
                base_dir=tmp,
                browser_factory=lambda _profile_id: FakeDriver(),
                collectors={
                    "profile": StaticProfileCollector(),
                    "video": StaticVideoCollector(),
                    "comment": collector,
                    "search": object(),
                },
            )
            service.router._wait_for_page = lambda *_args, **_kwargs: True
            driver = FakeDriver()
            target_url = "https://www.tiktok.com/@creator/video/123"
            driver.get(target_url)

            comments, evidence = service.router._collect_comments_with_retry(
                driver,
                {
                    "id": "ct_target",
                    "video_id": "123",
                    "video_url": target_url,
                },
                GrowthTaskConfig(test_mode=True, comment_retry_attempts=2),
                "comment_scan",
            )
            with service.storage.connect() as conn:
                events = [
                    dict(row)
                    for row in conn.execute("SELECT event, payload FROM growth_events WHERE event LIKE 'comment_scan_url_mismatch%'")
                ]

        self.assertEqual(collector.calls, 2)
        self.assertEqual(driver.visited[-1], target_url)
        self.assertEqual(len(comments), 1)
        self.assertEqual(evidence.final_url, target_url)
        self.assertTrue(any(row["event"] == "comment_scan_url_mismatch_retry" for row in events))

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

    def test_seller_promo_comment_is_not_scored_as_customer_lead(self):
        scorer = CandidateUserScorer.__new__(CandidateUserScorer)
        scorer.intent_classifier = RuleBasedCommentIntentClassifier()

        score, tags, status = scorer.score_candidate(
            {
                "username": "wig_brand",
                "comment_text": "Link in my bio. Use 26% off Code: HAIR26",
                "comment_likes": 9,
                "reply_count": 2,
                "views": 150000,
                "video_comments": 1200,
            },
            Counter({"wig_brand": 1}),
            custom_intent_keywords=["link"],
        )

        self.assertEqual(score, 0)
        self.assertEqual(status, "low_value")
        self.assertIn("excluded_seller_promo", tags)
        manager = OperationLeadManager.__new__(OperationLeadManager)
        class Config:
            intent_keywords = ["link"]

        intent_type, confidence, evidence = manager.detect_intent(
            {"comment_text": "Link in my bio. Use 26% off Code: HAIR26"},
            Config(),
        )
        self.assertEqual(intent_type, "")
        self.assertEqual(confidence, 0)
        self.assertIn("自促", evidence)

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

    def test_standard_outreach_policy_skips_low_intent_and_limits_normal_to_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            manager = service.router.operation_leads
            class Config:
                enable_action_queue = True
                enable_comment_queue = True
                enable_follow_queue = True
                enable_dm_queue = True
                enable_standard_outreach_policy = True
                min_lead_score_for_action = 50
                active_batch_id = "gb_policy"

            low_count = manager._create_actions(
                "lead-low",
                {
                    "username": "viewer_low",
                    "profile_url": "https://www.tiktok.com/@viewer_low",
                    "source_path": "https://www.tiktok.com/@creator/video/1",
                    "qualify_score": 45,
                    "comment_text": "nice",
                },
                "engaged_commenter",
                "normal",
                Config(),
            )
            normal_count = manager._create_actions(
                "lead-normal",
                {
                    "username": "buyer_normal",
                    "profile_url": "https://www.tiktok.com/@buyer_normal",
                    "source_path": "https://www.tiktok.com/@creator/video/2",
                    "qualify_score": 55,
                    "comment_text": "where is the link",
                },
                "找链接/入口",
                "normal",
                Config(),
            )
            intent_low_count = manager._create_actions(
                "lead-intent-low",
                {
                    "username": "buyer_intent_low",
                    "profile_url": "https://www.tiktok.com/@buyer_intent_low",
                    "source_path": "https://www.tiktok.com/@creator/video/3",
                    "qualify_score": 10,
                    "comment_text": "need the link",
                },
                "找链接/入口",
                "normal",
                Config(),
            )
            actions = service.storage.list_action_queue(limit=20)

            self.assertEqual(low_count, 0)
            self.assertEqual(normal_count, 1)
            self.assertEqual(intent_low_count, 1)
            self.assertEqual([row["action_type"] for row in actions], ["comment_reply", "comment_reply"])
            self.assertEqual({row["batch_id"] for row in actions}, {"gb_policy"})
            self.assertIn("product page", actions[0]["suggested_text"])

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

    def test_profile_preflight_quarantines_kernel_mismatch_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            group_manager = FakeProfileGroupManager()
            checker = ProfilePreflightChecker(
                service.storage,
                ProfilePreflightConfig(max_workers=1, page_load_timeout_seconds=1, wait_after_open_seconds=0),
                driver_factory=lambda _profile: (None, None, "ixBrowser open_profile failed: code=2014 message=当前版本仅支持 138 内核打开"),
                group_manager=group_manager,
            )

            available, summary = checker.available_profiles([{"profile_id": "24909", "group_name": "United States"}])

            self.assertEqual(available, [])
            self.assertEqual(summary["errors"]["IXBROWSER_KERNEL_MISMATCH"], 1)
            self.assertEqual(group_manager.moves, [("24909", "IXBROWSER_KERNEL_MISMATCH")])
            health = {row["profile_id"]: row for row in service.storage.list_profile_health(limit=10)}
            self.assertEqual(health["24909"]["status"], "cooldown")
            self.assertEqual(health["24909"]["last_error_code"], "IXBROWSER_KERNEL_MISMATCH")

    def test_profile_preflight_detects_tiktok_account_setup_modal(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            group_manager = FakeProfileGroupManager()
            driver = FakeProfilePreflightDriver("For You")
            driver.script_results = [
                {
                    "url": "https://www.tiktok.com/",
                    "title": "TikTok - Make Your Day",
                    "loginGate": True,
                    "loggedIn": False,
                    "exactLoginButton": False,
                    "dialogLoginGate": False,
                    "forcedLoginText": False,
                    "accountSetupGate": True,
                    "pumbaaCtx": "login=1,ftc=0,cb_enabled=0",
                    "labels": ["got it"],
                    "dialogs": ["how face or voice data is used important things to know got it"],
                    "sample": "how face or voice data is used important things to know got it",
                }
            ]
            checker = ProfilePreflightChecker(
                service.storage,
                ProfilePreflightConfig(max_workers=1, page_load_timeout_seconds=1, wait_after_open_seconds=0),
                driver_factory=lambda _profile: (driver, (FakeReleaseManager(), "setup-modal"), ""),
                group_manager=group_manager,
            )
            checker._executor._release = lambda _handle: None

            available, summary = checker.available_profiles([{"profile_id": "12345", "group_name": "US"}])

            self.assertEqual(available, [])
            self.assertEqual(summary["errors"]["LOGIN_REQUIRED"], 1)
            self.assertEqual(group_manager.moves, [("12345", "LOGIN_REQUIRED")])

    def test_profile_preflight_timeout_marks_profile_unavailable_without_quarantine(self):
        class FakeFuture:
            def __init__(self):
                self.cancelled = False

            def cancel(self):
                self.cancelled = True
                return True

        class FakePool:
            def __init__(self, max_workers):
                self.max_workers = max_workers
                self.future = FakeFuture()
                self.submitted = []
                self.shutdown_calls = []
                pools.append(self)

            def submit(self, fn, *args):
                self.submitted.append((fn, args))
                return self.future

            def shutdown(self, wait=True, cancel_futures=False):
                self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})

        def fake_as_completed(_futures, timeout=None):
            timeouts.append(timeout)
            raise FuturesTimeout()

        pools = []
        timeouts = []
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            group_manager = FakeProfileGroupManager()
            with patch("ReachOps.workbench.profile_preflight.ThreadPoolExecutor", FakePool), patch(
                "ReachOps.workbench.profile_preflight.as_completed", fake_as_completed
            ):
                checker = ProfilePreflightChecker(
                    service.storage,
                    ProfilePreflightConfig(
                        max_workers=1,
                        page_load_timeout_seconds=1,
                        wait_after_open_seconds=0,
                        total_timeout_seconds=0.1,
                    ),
                    driver_factory=lambda _profile: (
                        BlockingProfilePreflightDriver(),
                        (FakeReleaseManager(), "slow"),
                        "",
                    ),
                    group_manager=group_manager,
                )

                available, summary = checker.available_profiles([{"profile_id": "12346", "group_name": "US"}])

            self.assertEqual(available, [])
            self.assertEqual(timeouts, [0.1])
            self.assertEqual(len(pools), 1)
            self.assertEqual(pools[0].max_workers, 1)
            self.assertEqual(len(pools[0].submitted), 1)
            self.assertTrue(pools[0].future.cancelled)
            self.assertEqual(pools[0].shutdown_calls, [{"wait": False, "cancel_futures": True}])
            self.assertEqual(summary["errors"]["PROFILE_PREFLIGHT_TIMEOUT"], 1)
            self.assertEqual(group_manager.moves, [])
            health = {row["profile_id"]: row for row in service.storage.list_profile_health(limit=10)}
            self.assertEqual(health["12346"]["status"], "cooldown")
            self.assertEqual(health["12346"]["last_error_code"], "PROFILE_PREFLIGHT_TIMEOUT")

    def test_profile_preflight_retains_successful_browser_session_for_handoff(self):
        class RetainManager:
            def __init__(self, session):
                self._sessions = {"inst-1": session}
                self.released = []

            def release(self, instance_id, reason):
                self.released.append((instance_id, reason))

        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            driver = FakeProfilePreflightDriver("Messages Inbox Profile Upload")
            session = type("Session", (), {"instance_id": "inst-1", "driver": driver})()
            manager = RetainManager(session)
            checker = ProfilePreflightChecker(
                service.storage,
                ProfilePreflightConfig(
                    max_workers=1,
                    wait_after_open_seconds=0,
                    close_browser_after_check=True,
                    retain_successful_browser_after_check=True,
                ),
                driver_factory=lambda _profile: (driver, (manager, "inst-1"), ""),
                group_manager=FakeProfileGroupManager(),
            )

            available, summary = checker.available_profiles([{"profile_id": "p1", "group_name": "US"}])

        self.assertEqual([row["profile_id"] for row in available], ["p1"])
        self.assertEqual(summary["available"], 1)
        self.assertTrue(summary["results"][0]["session_retained"])
        self.assertEqual(summary["results"][0]["close_action"], "preflight_ok_retained")
        self.assertIs(checker.retained_sessions()["p1"], session)
        self.assertEqual(manager.released, [])

    def test_profile_preflight_staggers_profile_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GrowthIntelligenceService(base_dir=tmp)
            launch_times = []

            def factory(profile):
                launch_times.append(time.time())
                return FakeProfilePreflightDriver("Messages Inbox Profile Upload"), (FakeReleaseManager(), profile["profile_id"]), ""

            checker = ProfilePreflightChecker(
                service.storage,
                ProfilePreflightConfig(
                    max_workers=2,
                    page_load_timeout_seconds=1,
                    wait_after_open_seconds=0,
                    total_timeout_seconds=2,
                    launch_stagger_seconds=0.03,
                ),
                driver_factory=factory,
                group_manager=FakeProfileGroupManager(),
            )
            checker._executor._release = lambda _handle: None

            checker.available_profiles(
                [
                    {"profile_id": "a", "group_name": "US"},
                    {"profile_id": "b", "group_name": "US"},
                ]
            )

            self.assertEqual(len(launch_times), 2)
            self.assertGreaterEqual(launch_times[1] - launch_times[0], 0.02)

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

    def test_ix_profile_group_manager_accepts_camel_case_group_fields(self):
        client = FakeIxProfileClient(groups=[{"groupId": 296456, "groupName": "封禁账号"}])
        manager = IxProfileGroupManager(client_factory=lambda: client)

        result = manager.move_profile_to_quarantine("24909", reason="IXBROWSER_KERNEL_MISMATCH")

        self.assertTrue(result.ok)
        self.assertEqual(result.group_id, "296456")
        self.assertEqual(client.created, [])
        self.assertEqual(client.moves, [(24909, 296456)])

    def test_ix_profile_group_manager_accepts_wrapped_group_list_response(self):
        class WrappedGroupClient(FakeIxProfileClient):
            def get_group_list(self, page=1, limit=100):
                rows = super().get_group_list(page=page, limit=limit)
                return {"data": {"records": rows, "totalCount": len(self.groups)}}

        client = WrappedGroupClient(groups=[{"groupId": 296456, "groupName": "封禁账号"}])
        manager = IxProfileGroupManager(client_factory=lambda: client)

        result = manager.move_profile_to_quarantine("24910", reason="IXBROWSER_KERNEL_MISMATCH")

        self.assertTrue(result.ok)
        self.assertEqual(result.group_id, "296456")
        self.assertEqual(client.created, [])
        self.assertEqual(client.moves, [(24910, 296456)])

    def test_ix_profile_group_manager_creates_banned_group_when_missing(self):
        client = FakeIxProfileClient(groups=[], create_response={"data": {"id": 888}})
        manager = IxProfileGroupManager(client_factory=lambda: client)

        result = manager.move_profile_to_quarantine("22377", reason="COMMENT_ACCESS_GATED")

        self.assertTrue(result.ok)
        self.assertEqual(result.group_id, "888")
        self.assertEqual(client.created, [("封禁账号", 0)])
        self.assertEqual(client.moves, [(22377, 888)])

    def test_ix_profile_group_manager_reports_local_api_error_before_group_missing(self):
        class UnavailableGroupClient(FakeIxProfileClient):
            code = 1
            message = "connection refused"

            def get_group_list(self, page=1, limit=100):
                return None

            def create_group(self, title, sort=0):
                return None

        client = UnavailableGroupClient()
        manager = IxProfileGroupManager(client_factory=lambda: client)

        result = manager.move_profile_to_quarantine("24915", reason="IXBROWSER_KERNEL_MISMATCH")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "IX_GROUP_CREATE_FAILED")
        self.assertIn("connection refused", result.error_message)

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

    def test_live_action_executor_preflight_sidecar_does_not_claim_comment_submission(self):
        class ScreenshotDriver:
            current_url = "https://www.tiktok.com/@creator/video/123"
            title = "TikTok test page"

            def save_screenshot(self, path):
                Path(path).write_bytes(b"png")
                return True

        with tempfile.TemporaryDirectory() as tmp:
            executor = TikTokSeleniumActionExecutor(
                TikTokActionExecutorConfig(evidence_dir=tmp, preflight_only=True)
            )
            path = executor._capture_evidence(
                ScreenshotDriver(),
                {"id": "action-1", "action_type": "comment_reply", "target_url": "https://www.tiktok.com/@creator/video/123"},
                "profile-1",
                "ok",
                expected_text="hi",
                comment_visible_confirmed=True,
            )

            payload = json.loads(Path(f"{path}.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["preflight_only"])
            self.assertEqual(payload["submitted_text"], "")
            self.assertFalse(payload["comment_visible_confirmed"])

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

    def test_live_action_executor_blocks_third_party_login_click_targets(self):
        class FacebookLoginElement:
            text = "Continue with Facebook"
            clicked = False

            def get_attribute(self, attr):
                values = {
                    "aria-label": "Continue with Facebook",
                    "href": "https://www.facebook.com/login",
                    "data-e2e": "login-provider",
                }
                return values.get(attr, "")

            def click(self):
                self.clicked = True

        element = FacebookLoginElement()
        executor = TikTokSeleniumActionExecutor()

        with self.assertRaisesRegex(RuntimeError, "THIRD_PARTY_LOGIN_GUARD"):
            executor._click(element)

        self.assertFalse(element.clicked)
        self.assertEqual(executor._classify_exception(RuntimeError("THIRD_PARTY_LOGIN_GUARD: facebook")), "LOGIN_REQUIRED")

    def test_live_action_executor_safe_dispatch_refuses_facebook_login_provider(self):
        class FacebookLoginElement:
            text = "Log in with Facebook"

            def get_attribute(self, attr):
                return "Log in with Facebook" if attr in {"innerText", "aria-label"} else ""

            def click(self):
                raise AssertionError("facebook login provider must not be clicked")

        class DispatchDriver:
            dispatched = False

            def execute_script(self, *_args):
                self.dispatched = True
                return True

        driver = DispatchDriver()
        executor = TikTokSeleniumActionExecutor()

        self.assertFalse(executor._click_or_dispatch(driver, FacebookLoginElement()))
        self.assertFalse(driver.dispatched)

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
            "产品链接能自动生成获客任务和可执行来源",
            "达人链接和话题能自动生成获客任务",
            "AI/规则能生成产品分析",
            "外部 AI 故障可自动降级规则策略",
            "系统能自动生成受众画像",
            "AI/规则能生成意图分类和话术建议",
            "系统能自动规划来源",
            "刷新分组能读取 ixBrowser 配置分组列表",
            "选择哪个分组就实际用哪个分组执行",
            "网页端通过服务端本地 API 调用指纹浏览器执行获客",
            "能识别并排除异常账号",
            "客户端按钮和设置接入真实执行链路",
            "客户可见设置都有执行证据映射",
            "客户能看到成功失败换号和错误码",
            "开始任务后日志能实时显示执行进度",
            "异常不弹窗卡死",
            "客户端文案面向运营用户",
            "漏斗只显示本轮 Campaign",
            "能识别页面打不开和无评论",
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
            "导出内容包含客户池动作漏斗和错误统计",
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
                },
                {
                    "name": "客户端交付验收门禁不会把环境阻断当通过",
                    "status": "pending_external_validation",
                    "evidence": {"reason": "needs client acceptance readiness"},
                }
            ],
        }

        report = build_goal_status_report(audit)

        self.assertEqual(report["status"], "ready_for_external_validation")
        self.assertIn("授权允许时能真实执行", report["pending_external_validation"])
        self.assertIn("真实 TikTok 平台提交", report["pending_external_validation"])
        self.assertIn("客户端交付验收门禁不会把环境阻断当通过", report["pending_external_validation"])
        stage3 = next(row for row in report["stages"] if row["name"] == "阶段 3：真实执行")
        stage5 = next(row for row in report["stages"] if row["name"] == "阶段 5：独立打包")
        self.assertEqual(stage3["status"], "pending_external_validation")
        self.assertEqual(stage5["status"], "pending_external_validation")
        self.assertEqual(report["summary"]["final_failed"], 0)
        self.assertEqual(report["summary"]["final_pending_external_validation"], 3)

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
                        "产品链接能自动生成获客任务和可执行来源",
                        "达人链接和话题能自动生成获客任务",
                        "AI/规则能生成产品分析",
                        "外部 AI 故障可自动降级规则策略",
                        "系统能自动生成受众画像",
                        "AI/规则能生成意图分类和话术建议",
                        "系统能自动规划来源",
                        "刷新分组能读取 ixBrowser 配置分组列表",
                        "选择哪个分组就实际用哪个分组执行",
                        "网页端通过服务端本地 API 调用指纹浏览器执行获客",
                        "能识别并排除异常账号",
                        "客户端按钮和设置接入真实执行链路",
                        "客户可见设置都有执行证据映射",
                        "客户能看到成功失败换号和错误码",
                        "开始任务后日志能实时显示执行进度",
                        "异常不弹窗卡死",
                        "客户端文案面向运营用户",
                        "漏斗只显示本轮 Campaign",
                        "能识别页面打不开和无评论",
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
                        "导出内容包含客户池动作漏斗和错误统计",
                        "独立配置/数据/授权目录存在",
                        "Windows 打包入口存在",
                        "升级清单和安装校验机制可用",
                        "项目结构无缓存临时备份冗余文件",
                    ]
                ],
            },
            acceptance_summary={
                "status": "passed",
                "delivery_audit": {
                    "status": "ok",
                    "passed": 26,
                    "failed": 0,
                    "pending_external_validation": 3,
                    "resolved_external_validation": 3,
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
                "repository_cleanliness": {
                    "status": "passed",
                    "passed": True,
                    "forbidden_count": 0,
                    "json_path": "reports/reachops_acceptance/current/repository_cleanliness_payload.json",
                },
                "windows_package_preflight": {
                    "status": "ready_for_windows_build",
                    "ready_for_windows_build": True,
                    "final_delivery_ready": False,
                    "build_contract": {
                        "default_build_requires_installer": True,
                        "skip_installer_is_non_final": True,
                    },
                    "json_path": "reports/reachops_acceptance/current/windows_package_preflight.json",
                },
                "client_delivery": {
                    "status": "passed",
                    "readiness": "pass",
                    "contract_ok": True,
                    "acceptance_ready": True,
                    "final_delivery_ready": True,
                    "failed_checks": [],
                    "json_path": "reports/reachops_acceptance/current/client_delivery.json",
                },
                "live_readiness": {"status": "ready", "ready": True, "no_browser_started": False, "no_submit": True},
                "live_preflight": {
                    "status": "completed",
                    "preflight_action_statuses": {
                        "comment_reply": [{"status": "success"}],
                        "follow_review": [{"status": "success"}],
                        "dm_review": [{"status": "success"}],
                    },
                    "missing_preflight_action_types": [],
                },
                "live_submit": {
                    "status": "completed",
                    "executor_mode": "platform_selenium",
                    "platform_validation": True,
                    "passed": True,
                    "live_submit": True,
                    "activation_status_loaded": True,
                    "summary": {
                        "selected_actions": 3,
                        "success": 3,
                        "failed": 0,
                        "skipped": 0,
                        "results": [
                            {"action_type": "comment_reply", "status": "success", "action_id": "comment_reply-1", "profile_id": "10001"},
                            {"action_type": "follow_review", "status": "success", "action_id": "follow_review-1", "profile_id": "10001"},
                            {"action_type": "dm_review", "status": "success", "action_id": "dm_review-1", "profile_id": "10001"},
                        ],
                    },
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
                "final_acceptance_gate": {
                    "status": "passed",
                    "final_delivery_ready": True,
                    "failed_checks": [],
                    "json_path": "reports/reachops_acceptance/current/final_acceptance_gate.json",
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

            batch = service.storage.latest_collection_batch_for_campaign(campaign_id)
            batch_id = str(batch.get("id") or "")
            queued_actions = service.storage.list_action_queue(limit=10, batch_id=batch_id)
            self.assertTrue(queued_actions)
            action = queued_actions[0]
            service.storage.set_active_collection_batch(batch_id)
            duplicate_gate = RiskGate().evaluate(
                {
                    "id": action["id"],
                    "action_type": action["action_type"],
                    "status": "approved",
                    "execution_confirmed": 1,
                },
                {"profile_id": "profile-export-risk", "group_name": "US"},
                live_submit=True,
                duplicate_text_status={"ok": False, "code": "DUPLICATE_ACTION_TEXT", "message": "same rendered text already used"},
            )
            service.storage.create_outreach_execution(
                action["id"],
                action["action_type"],
                action["target_username"],
                status="skipped",
                profile_id="profile-export-risk",
                error_code="DUPLICATE_ACTION_TEXT",
                error_message="same rendered text already used",
                risk_gate=duplicate_gate,
            )

            artifacts = workflow.export_campaign_artifacts(campaign_id=campaign_id)
            for key in ["json_path", "sources_csv_path", "customers_csv_path", "actions_csv_path", "executions_csv_path"]:
                self.assertTrue(os.path.exists(artifacts[key]), key)

            with open(artifacts["json_path"], "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertEqual(payload["campaign"]["id"], campaign_id)
            self.assertEqual(payload["funnel"]["campaign_id"], campaign_id)
            self.assertEqual(len(payload["candidate_users"]), 1)
            self.assertGreaterEqual(len(payload["operation_leads"]), 1)
            self.assertGreaterEqual(len(payload["action_queue"]), 1)
            self.assertIn("outreach_executions", payload)
            self.assertIn("execution_summary", payload)
            self.assertEqual(payload["execution_summary"]["total"], len(payload["outreach_executions"]))
            self.assertIn("error_counts", payload["execution_summary"])
            self.assertTrue(any("DUPLICATE_ACTION_TEXT" in row.get("risk_gate_summary", "") for row in payload["outreach_executions"]))
            self.assertTrue(any(row.get("risk_gate_next_step") == "改写或轮换话术后重试" for row in payload["outreach_executions"]))
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

            with open(artifacts["executions_csv_path"], "r", encoding="utf-8") as fh:
                execution_reader = csv.DictReader(fh)
                self.assertIn("action_type", execution_reader.fieldnames or [])
                self.assertIn("profile_id", execution_reader.fieldnames or [])
                self.assertIn("evidence_path", execution_reader.fieldnames or [])
                self.assertIn("risk_gate_summary", execution_reader.fieldnames or [])
                self.assertIn("risk_gate_next_step", execution_reader.fieldnames or [])
                execution_rows = list(execution_reader)
            self.assertTrue(any("DUPLICATE_ACTION_TEXT" in row["risk_gate_summary"] for row in execution_rows))

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

            for key in ["json_path", "sources_csv_path", "customers_csv_path", "actions_csv_path", "executions_csv_path"]:
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

    def test_comma_separated_promotion_keywords_become_individual_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            target = "skincare,skincareroutine,skintok,glassskin,glowingskin"
            plan = service.create_campaign_plan(target, max_sources=5)

            self.assertEqual(plan["campaign"]["input_type"], "keyword")
            self.assertEqual(plan["campaign"]["product_name"], "skincare")
            source_values = [row["source_value"] for row in plan["sources"]]
            self.assertEqual(source_values[:5], ["skincare", "skincareroutine", "skintok", "glassskin", "glowingskin"])
            self.assertNotIn(target, source_values)
            strategy_sources = [row["source_value"] for row in plan["strategy"]["source_expansion"]]
            self.assertIn("skincare", strategy_sources)
            self.assertIn("skintok", plan["persona"]["search_keywords"])

    def test_direct_tiktok_video_link_stays_content_url_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            target = "https://www.tiktok.com/@creator/video/123"
            plan = service.create_campaign_plan(target, max_sources=3)

            self.assertEqual(plan["campaign"]["input_type"], "content_url")
            self.assertEqual(
                [(row["source_type"], row["source_value"]) for row in plan["sources"][:1]],
                [("content_url", target)],
            )
            self.assertNotIn(("creator_url", target), [(row["source_type"], row["source_value"]) for row in plan["sources"]])

    def test_beauty_social_terms_use_beauty_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)

            for target in ["skintok", "glassskin", "skinbarrier", "hyperpigmentation", "kbeauty"]:
                with self.subTest(target=target):
                    plan = service.create_campaign_plan(target, max_sources=2)

                    self.assertEqual(plan["campaign"]["category"], "beauty")
                    self.assertEqual(plan["strategy"]["product_analysis"]["category"], "beauty")
                    self.assertIn("beauty routine", plan["persona"]["interests"])
                    self.assertTrue(any(row["source_type"] == "keyword" for row in plan["sources"]))

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
            self.assertFalse(
                any(row["source_type"] == "keyword" and "amazon.com" in row["source_value"].lower() for row in plan["sources"])
            )
            self.assertFalse(
                any(row["source_type"] == "keyword" and row["source_value"].lower().startswith(("http://", "https://")) for row in plan["sources"])
            )
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

    def test_product_url_filters_low_signal_single_word_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan(
                "https://www.amazon.com/BPc-157-1000Mcg-120-Count-2pcs/dp/B0H1LS443N/ref=sr_1_2?keywords=BPC-157",
                max_sources=26,
            )

        source_values = [str(row["source_value"]) for row in plan["sources"]]
        self.assertTrue(any("BPc 157 1000Mcg 120 Count 2pcs" in value for value in source_values))
        self.assertNotIn("1000Mcg", source_values)
        self.assertNotIn("Count", source_values)
        self.assertNotIn("2pcs", source_values)

    def test_router_never_opens_external_product_url_as_topic_source(self):
        router = GrowthTaskRouter.__new__(GrowthTaskRouter)

        urls = router._topic_url_candidates(
            "keyword",
            "https://www.amazon.com/Retinol-Anti-Aging-Face-Serum/dp/B0ABC12345?tag=test",
        )

        self.assertTrue(urls)
        self.assertTrue(all(url.startswith("https://www.tiktok.com/") for url in urls))
        self.assertTrue(any("search" in url for url in urls))
        self.assertFalse(any("amazon.com" in url for url in urls))
        self.assertTrue(any("Retinol" in url or "Retinol%20Anti" in url for url in urls))

    def test_router_closes_extra_non_tiktok_product_tabs(self):
        class SwitchTo:
            def __init__(self, driver):
                self.driver = driver

            def window(self, handle):
                self.driver.current_window_handle = handle
                self.driver.current_url = self.driver.urls[handle]

        class MultiTabDriver:
            def __init__(self):
                self.urls = {
                    "main": "https://www.tiktok.com/search/video?q=serum",
                    "product": "https://www.amazon.com/Retinol-Anti-Aging-Face-Serum/dp/B0ABC12345",
                    "video": "https://www.tiktok.com/@creator/video/123",
                }
                self.window_handles = ["main", "product", "video"]
                self.current_window_handle = "main"
                self.current_url = self.urls["main"]
                self.switch_to = SwitchTo(self)
                self.closed = []

            def close(self):
                handle = self.current_window_handle
                self.closed.append(handle)
                self.window_handles = [item for item in self.window_handles if item != handle]

        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            driver = MultiTabDriver()

            closed = service.router._close_non_tiktok_tabs(driver, source_id="source-1", profile_id="p1")

        self.assertEqual(closed, 1)
        self.assertEqual(driver.closed, ["product"])
        self.assertEqual(driver.current_window_handle, "main")
        self.assertNotIn("product", driver.window_handles)

    def test_router_blocks_external_direct_collection_urls(self):
        class FakeStorage:
            def __init__(self):
                self.errors = []

            def log_error(self, code, message, source_id, creator_id="", profile_id=""):
                self.errors.append(
                    {
                        "code": code,
                        "message": message,
                        "source_id": source_id,
                        "profile_id": profile_id,
                    }
                )

        router = GrowthTaskRouter.__new__(GrowthTaskRouter)
        router.storage = FakeStorage()
        datasource = type("Source", (), {"type": "content_url", "value": "https://www.amazon.com/p/demo", "id": "as_1"})()

        result = router._run_datasource(datasource, FakeDriver(), GrowthTaskConfig(test_mode=True), "p1")

        self.assertFalse(result)
        self.assertEqual(router.storage.errors[0]["code"], "NON_TIKTOK_SOURCE_BLOCKED")

    def test_common_product_links_extract_readable_product_names(self):
        targets = [
            (
                "https://brand.example.com/products/portable-dog-water-bottle?variant=123",
                "Portable Dog Water Bottle",
            ),
            (
                "https://www.etsy.com/listing/123456789/handmade-ceramic-matcha-bowl",
                "Handmade Ceramic Matcha Bowl",
            ),
            (
                "https://www.walmart.com/ip/Owala-FreeSip-Insulated-Stainless-Steel-Water-Bottle/123456",
                "Owala FreeSip Insulated Stainless Steel Water Bottle",
            ),
            (
                "https://shop.app/products/skin-barrier-serum",
                "Skin Barrier Serum",
            ),
            (
                "www.amazon.com/Owala-FreeSip-Sway-Stainless-30-oz/dp/B0FJZDV6BH",
                "Owala FreeSip Sway Stainless 30 oz",
            ),
            (
                "https://brand.example.com/item/123456?title=mini+portable+projector",
                "Mini Portable Projector",
            ),
            (
                "https://www.tiktok.com/product/skin-barrier-serum-1729384756123",
                "Skin Barrier Serum",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            for target, expected_name in targets:
                with self.subTest(target=target):
                    plan = service.create_campaign_plan(target, max_sources=6)

                    self.assertEqual(plan["campaign"]["input_type"], "product_url")
                    self.assertEqual(plan["campaign"]["product_name"], expected_name)
                    source_pairs = [(row["source_type"], row["source_value"]) for row in plan["sources"]]
                    self.assertIn(("keyword", expected_name), source_pairs)
                    self.assertIn(("keyword", f"{expected_name} review"), source_pairs)
                    self.assertNotIn(("product_url", target), source_pairs)
                    self.assertTrue(any(row["source_type"] == "hashtag" for row in plan["sources"]))

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

    def test_action_router_allows_unlimited_comment_run_when_limits_are_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            batch = service.storage.create_collection_batch(1, profile_group="US", initial_status="completed")
            for index in range(25):
                item = ActionQueueItem(
                    id=f"aq_unlimited_{index}",
                    lead_id=f"lead_{index}",
                    action_type="comment_reply",
                    target_username=f"user_{index}",
                    target_url=f"https://www.tiktok.com/@creator/video/123?comment={index}",
                    suggested_text="Thanks for asking.",
                    status="pending_review",
                )
                action_id, _ = service.storage.upsert_action_queue_item(item)
                with service.storage.connect() as conn:
                    conn.execute("UPDATE action_queue SET batch_id=? WHERE id=?", (batch.id, action_id))

            result = GrowthWorkflowService(service).run_action_router(
                [{"profile_id": "exec-1", "group_name": "US"}],
                config=ActionRouterConfig(
                    max_workers=1,
                    per_profile_action_limit=25,
                    per_profile_daily_limit=0,
                    per_profile_hour_limit=0,
                    per_profile_video_hour_limit=0,
                    action_types=["comment_reply"],
                    dry_run=True,
                    batch_id=batch.id,
                ),
                fixture_outcomes=[{"action_type": "comment_reply", "status": "success"}],
                limit=25,
                export_report=False,
            )

            self.assertEqual(result["selected_actions"], 25)
            self.assertEqual(result["success"], 25)
            self.assertEqual(result["errors"], {})
            self.assertEqual(service.storage.list_daily_quota(limit=10), [])

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
            with patch.dict(os.environ, {"REACHOPS_REQUIRE_ACTIVATION": "1"}, clear=False):
                result = GrowthWorkflowService(service).run_action_router(
                    [{"profile_id": "exec-1", "group_name": "US"}],
                    config=ActionRouterConfig(
                        max_workers=1,
                        per_profile_action_limit=10,
                        action_types=["comment_reply"],
                        dry_run=False,
                        live_preflight_only=False,
                        allow_live_submit=True,
                        auto_approve=True,
                        auto_confirm=True,
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
                    auto_approve=True,
                    auto_confirm=True,
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

    def test_live_submit_rejects_uri_evidence_even_when_activation_status_enables_feature(self):
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
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_EVIDENCE_MISSING"], 1)

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
                    auto_approve=True,
                    auto_confirm=True,
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
            plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=1)
            service.run_collection(
                [{"type": "creator_url", "value": "https://www.tiktok.com/@beauty_creator"}],
                [{"profile_id": "discovery-1", "group_name": "US"}],
                GrowthTaskConfig(campaign_id=plan["campaign"]["id"], max_videos_per_creator=1, max_comments_per_video=10, test_mode=True),
            )
            comment_action = next(row for row in service.storage.list_action_queue(limit=10) if row["action_type"] == "comment_reply")
            evidence_path = Path(tmp) / "comment-evidence.png"
            evidence_path.write_bytes(b"png")
            with open(f"{evidence_path}.json", "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                        "action_type": "comment_reply",
                        "submitted_text": comment_action["suggested_text"],
                        "comment_visible_confirmed": True,
                    },
                    fh,
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
                    auto_approve=True,
                    auto_confirm=True,
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

    def test_live_submit_rejects_local_comment_evidence_when_text_mismatches(self):
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
                        "submitted_text": "different text",
                        "comment_visible_confirmed": True,
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
                    auto_approve=True,
                    auto_confirm=True,
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
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["errors"]["LIVE_SUBMIT_EVIDENCE_MISSING"], 1)

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
            comment_action = next(row for row in service.storage.list_action_queue(limit=10) if row["action_type"] == "comment_reply")
            evidence_path = Path(tmp) / "device-bound-comment-evidence.png"
            evidence_path.write_bytes(b"png")
            with open(f"{evidence_path}.json", "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "screenshot_sha256": hashlib.sha256(b"png").hexdigest(),
                        "action_type": "comment_reply",
                        "profile_id": "exec-1",
                        "action_id": comment_action["id"],
                        "current_url": "https://www.tiktok.com/@beauty_creator/video/123",
                        "submitted_text": comment_action["suggested_text"],
                        "comment_visible_confirmed": True,
                    },
                    fh,
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
                        "evidence_path": str(evidence_path),
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
            for index in range(3):
                item = ActionQueueItem(
                    id=f"aq_preflight_filter_{index}",
                    lead_id=f"preflight_lead_{index}",
                    action_type="comment_reply",
                    target_username=f"buyer_{index}",
                    target_url=f"https://www.tiktok.com/@creator/video/123?comment={index}",
                    suggested_text="Preflight reply",
                    status="pending_review",
                )
                action_id, _ = service.storage.upsert_action_queue_item(item)
                with service.storage.connect() as conn:
                    conn.execute("UPDATE action_queue SET batch_id=? WHERE id=?", (batch["id"], action_id))
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service
            app.workflow = GrowthWorkflowService(service)
            app.console = Console()
            app.root = Root()
            app.active_batch_id = batch["id"]
            app._current_snapshot = lambda: app.workflow.build_snapshot(campaign_id=plan["campaign"]["id"], batch_id=batch["id"])
            app._current_group_name = lambda: "US"
            app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
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

    def test_standalone_live_comment_uses_all_pending_actions_without_comment_limits(self):
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
            action_execution_mode_var = Value("真实提交")
            action_execution_live_confirm_var = Value(True)
            action_execution_workers_var = Value(1)
            action_execution_per_profile_var = Value(3)
            action_execution_hour_limit_var = Value(10)
            action_execution_video_hour_limit_var = Value(1)

            def refresh(self, _snapshot):
                return None

        class CaptureWorkflow:
            def __init__(self):
                self.config = None
                self.limit = None

            def run_action_router(self, _profiles, config=None, platform_executor=None, limit=100, export_report=True, batch_id=""):
                self.config = config
                self.limit = limit
                return {
                    "selected_actions": limit,
                    "success": limit,
                    "failed": 0,
                    "skipped": 0,
                    "account_switched": 0,
                    "worker_count": 1,
                    "available_profile_count": 1,
                    "results": [],
                    "report": {"json_path": ""},
                }

            def build_snapshot(self, **_kwargs):
                return {}

        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            batch = service.storage.create_collection_batch(1, profile_group="US", initial_status="completed")
            for index in range(12):
                item = ActionQueueItem(
                    id=f"aq_live_{index}",
                    lead_id=f"live_lead_{index}",
                    action_type="comment_reply",
                    target_username=f"buyer_{index}",
                    target_url=f"https://www.tiktok.com/@creator/video/123?comment={index}",
                    suggested_text="Real reply",
                    status="pending_review",
                )
                action_id, _ = service.storage.upsert_action_queue_item(item)
                with service.storage.connect() as conn:
                    conn.execute("UPDATE action_queue SET batch_id=? WHERE id=?", (batch.id, action_id))

            workflow = CaptureWorkflow()
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service
            app.workflow = workflow
            app.console = Console()
            app.root = Root()
            app.active_batch_id = batch.id
            app._current_snapshot = lambda: {}
            app._current_group_name = lambda: "US"
            app._quick_comment_text = lambda: "Real reply"
            logs = []
            app._log = logs.append

            with patch(
                "ReachOps.workbench.profile_preflight.ProfilePreflightChecker.available_profiles",
                return_value=(
                    [{"profile_id": "exec-live", "group_name": "US"}],
                    {"checked": 1, "available": 1, "unavailable": 0, "errors": {}, "results": []},
                ),
            ):
                result = app._start_action_queue_processing(
                    "campaign-live",
                    "US",
                    [{"profile_id": "exec-live", "group_name": "US"}],
                )

        self.assertEqual(result["selected_actions"], 12)
        self.assertEqual(workflow.limit, 12)
        self.assertEqual(workflow.config.per_profile_action_limit, 12)
        self.assertEqual(workflow.config.per_profile_daily_limit, 0)
        self.assertEqual(workflow.config.per_profile_hour_limit, 0)
        self.assertEqual(workflow.config.per_profile_video_hour_limit, 0)
        self.assertEqual(workflow.config.action_types, ["comment_reply"])
        self.assertTrue(workflow.config.allow_live_submit)

    def test_standalone_logs_touch_skipped_when_no_action_queue(self):
        class Root:
            def after(self, _delay, callback=None):
                if callback:
                    callback()

        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        class Console:
            action_execution_mode_var = Value("预检，不提交")
            action_execution_live_confirm_var = Value(False)
            action_execution_workers_var = Value("1")
            action_execution_per_profile_var = Value("3")
            action_execution_hour_limit_var = Value("10")
            action_execution_video_hour_limit_var = Value("1")

            def refresh(self, *_args, **_kwargs):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            plan = service.create_campaign_plan("https://www.tiktok.com/@creator", max_sources=1)
            batch = service.storage.create_collection_batch(
                1,
                profile_group="US",
                campaign_id=plan["campaign"]["id"],
                initial_status="completed",
            )
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service
            app.workflow = GrowthWorkflowService(service)
            app.console = Console()
            app.root = Root()
            app.active_batch_id = batch.id
            app._current_snapshot = lambda: {}
            app._current_group_name = lambda: "US"
            logs = []
            app._log = logs.append

            result = app._start_action_queue_processing(
                plan["campaign"]["id"],
                "US",
                [{"profile_id": "exec-good", "group_name": "US"}],
            )

        self.assertEqual(result["selected_actions"], 0)
        self.assertTrue(any("TOUCH  skipped" in row and "no_submit=true" in row for row in logs))
        self.assertTrue(any("DONE   action_preflight skipped" in row for row in logs))

    def test_live_comment_seed_actions_allow_safe_low_score_candidate_with_fixed_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            batch = service.storage.create_collection_batch(1, profile_group="US", initial_status="completed")
            service.storage.set_active_collection_batch(batch.id)
            source = service.storage.upsert_datasource("tiktok", "keyword", "beauty")
            creator = service.storage.upsert_creator(
                DiscoveredCreator(
                    id="dc_seed",
                    source_id=source.id,
                    username="creator_seed",
                    profile_url="https://www.tiktok.com/@creator_seed",
                )
            )
            content, _ = service.storage.upsert_content(
                DiscoveredContent(
                    id="ct_seed",
                    creator_id=creator.id,
                    video_id="123456",
                    video_url="https://www.tiktok.com/@creator_seed/video/123456",
                    source_path="https://www.tiktok.com/@creator_seed/video/123456",
                )
            )
            service.storage.upsert_candidate(
                CandidateUser(
                    id="cu_seed",
                    content_id=content.id,
                    username="buyer_seed",
                    profile_url="https://www.tiktok.com/@buyer_seed",
                    comment_text="This looks useful",
                    qualify_score=25,
                    source_path=content.video_url,
                    status="low_value",
                )
            )
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service
            logs = []
            app._log = logs.append

            created = app._create_live_comment_seed_actions(
                batch.id,
                limit=1,
                min_score=20,
                fixed_comment_text="hihihi",
            )

            self.assertEqual(created, 1)
            actions = service.storage.list_action_queue(limit=10, batch_id=batch.id)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action_type"], "comment_reply")
            self.assertEqual(actions[0]["target_username"], "buyer_seed")

    def test_browser_crashed_forces_profile_cooldown_without_quarantine_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.router.profile_group_manager = FakeProfileGroupManager()

            service.router._record_blocking_profile_state(
                "profile-crashed",
                "US",
                "BROWSER_CRASHED",
                "chrome not reachable",
            )

            health = service.storage.list_profile_health(limit=10)

        row = next(item for item in health if item["profile_id"] == "profile-crashed")
        self.assertEqual(row["status"], "cooldown")
        self.assertEqual(row["last_error_code"], "BROWSER_CRASHED")
        self.assertEqual(service.router.profile_group_manager.moves, [])

    def test_target_quick_send_presets_and_modes_match_acceptance_plan(self):
        self.assertEqual(
            quick_send_preset("快速"),
            {"max_videos": 3, "max_comments": 20, "profile_limit": 3, "workers": 2, "task_interval": 3},
        )
        self.assertEqual(
            quick_send_preset("标准"),
            {"max_videos": 10, "max_comments": 50, "profile_limit": 6, "workers": 4, "task_interval": 8},
        )
        self.assertEqual(
            quick_send_preset("压测"),
            {"max_videos": 20, "max_comments": 100, "profile_limit": 10, "workers": 6, "task_interval": 1},
        )
        self.assertEqual(quick_send_mode_key("只采集"), "collect_only")
        self.assertEqual(quick_send_mode_key("采集 + 触达预检"), "preflight")
        self.assertEqual(quick_send_mode_key("采集 + 真实评论"), "live_comment")

    def test_quick_send_report_acceptance_lines_show_status_and_evidence_rule(self):
        console = GrowthOpsConsole.__new__(GrowthOpsConsole)
        snapshot = type(
            "Snapshot",
            (),
            {
                "campaign_funnel": {
                    "campaign_type": "content_url",
                    "content_found": 2,
                    "comment_users": 12,
                    "customer_leads": 1,
                    "outreach_actions": 3,
                    "preflight_ok": 3,
                    "failed": 0,
                },
                "executions": [{"status": "success"}],
                "errors": {},
            },
        )()

        lines = console._quick_send_acceptance_lines(snapshot)

        self.assertTrue(any("总体状态: passed" in row for row in lines))
        self.assertTrue(any("目标类型: content_url" in row for row in lines))
        self.assertTrue(any("no-submit 不计真实提交" in row for row in lines))

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

    def test_standalone_selected_profiles_excludes_health_cooldown_accounts_before_preflight(self):
        class Value:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Registry:
            groups = [{"group_id": "281726", "group_name": "Canada"}]

            def __init__(self):
                self.calls = []

            def refresh(self, include_profiles=False):
                raise AssertionError("groups are already loaded")

            def select_profiles(self, group, limit=50):
                self.calls.append((group, limit))
                return [
                    {"profile_id": "ca-cooldown", "group_id": "281726", "group_name": "Canada"},
                    {"profile_id": "ca-comment", "group_id": "281726", "group_name": "Canada comment"},
                    {"profile_id": "ca-publish", "group_id": "281726", "group_name": "Canada publish"},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.storage.force_profile_cooldown(
                "ca-cooldown",
                error_code="LOGIN_REQUIRED",
                error_message="login popup",
            )
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service
            app.profile_registry = Registry()
            app.profile_group_display_map = {}
            app.group_var = Value("Canada")
            app.console = type(
                "Console",
                (),
                {
                    "scan_profile_limit_var": Value(2),
                    "scan_profile_group_display_var": Value("Canada"),
                    "scan_profile_group_var": Value("Canada"),
                    "action_execution_group_var": Value(""),
                },
            )()
            logs = []
            app._log = logs.append

            selected = app._selected_profiles()

        self.assertEqual([row["profile_id"] for row in selected], ["ca-comment", "ca-publish"])
        self.assertEqual(app.profile_registry.calls[0], ("Canada", 50))
        self.assertTrue(any("candidates=3 selected=2 excluded=1" in row for row in logs))

    def test_standalone_rank_profiles_does_not_fallback_to_known_unusable_accounts(self):
        class Storage:
            def connect(self):
                raise RuntimeError("event history unavailable")

            def list_profile_health(self, limit=10000):
                return [
                    {
                        "profile_id": "bad-login",
                        "status": "cooldown",
                        "health_score": 20,
                        "consecutive_failures": 3,
                        "last_error_code": "LOGIN_REQUIRED",
                        "last_error_message": "LOGIN_REQUIRED",
                    },
                    {
                        "profile_id": "bad-kernel",
                        "status": "cooldown",
                        "health_score": 20,
                        "consecutive_failures": 3,
                        "last_error_code": "IXBROWSER_KERNEL_MISMATCH",
                        "last_error_message": "kernel mismatch",
                    },
                ]

        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app.service = type("Service", (), {"storage": Storage()})()
        logs = []
        app._log = logs.append

        selected = app._rank_profile_candidates(
            [
                {"profile_id": "bad-login", "group_name": "United States"},
                {"profile_id": "bad-kernel", "group_name": "United States"},
            ],
            2,
        )

        self.assertEqual(selected, [])
        self.assertTrue(any("avoid_restarting_known_unusable_profiles" in row for row in logs))

    def test_standalone_rank_profiles_excludes_recent_start_timeout_accounts(self):
        class Storage:
            def connect(self):
                raise RuntimeError("event history unavailable")

            def list_profile_health(self, limit=10000):
                return [
                    {
                        "profile_id": "slow-timeout",
                        "status": "degraded",
                        "health_score": 80,
                        "consecutive_failures": 2,
                        "last_error_code": "PROFILE_PREFLIGHT_TIMEOUT",
                        "last_error_message": "profile preflight exceeded 36.0s",
                    },
                    {
                        "profile_id": "page-open-failed",
                        "status": "degraded",
                        "health_score": 80,
                        "consecutive_failures": 1,
                        "last_error_code": "PAGE_OPEN_FAILED",
                        "last_error_message": "Timed out receiving message from renderer",
                    },
                ]

        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app.service = type("Service", (), {"storage": Storage()})()
        logs = []
        app._log = logs.append

        selected = app._rank_profile_candidates(
            [
                {"profile_id": "slow-timeout", "group_name": "United States"},
                {"profile_id": "page-open-failed", "group_name": "United States"},
                {"profile_id": "fresh-unknown", "group_name": "United States"},
            ],
            3,
        )

        self.assertEqual([row["profile_id"] for row in selected], ["fresh-unknown"])

    def test_standalone_rank_profiles_excludes_latest_account_repair_plan_profiles(self):
        class Storage:
            def connect(self):
                raise RuntimeError("event history unavailable")

            def list_profile_health(self, limit=10000):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp) / "reports" / "acceptance_remediation"
            plan_dir.mkdir(parents=True)
            (plan_dir / "latest_account_repair_plan.json").write_text(
                json.dumps(
                    {
                        "groups": [
                            {
                                "error": "IXBROWSER_KERNEL_MISMATCH",
                                "profile_ids": ["bad-kernel"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = type("Service", (), {"storage": Storage(), "base_dir": tmp})()
            logs = []
            app._log = logs.append

            selected = app._rank_profile_candidates(
                [
                    {"profile_id": "bad-kernel", "group_name": "United States"},
                    {"profile_id": "good-candidate", "group_name": "United States"},
                ],
                2,
            )

        self.assertEqual([row["profile_id"] for row in selected], ["good-candidate"])
        self.assertTrue(any("recent_unusable_excluded count=1" in row for row in logs))

    def test_standalone_rank_profiles_force_account_recheck_keeps_hard_failure_exclusion(self):
        class Storage:
            def connect(self):
                raise RuntimeError("event history unavailable")

            def list_profile_health(self, limit=10000):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp) / "reports" / "acceptance_remediation"
            plan_dir.mkdir(parents=True)
            (plan_dir / "latest_account_repair_plan.json").write_text(
                json.dumps(
                    {
                        "groups": [
                            {
                                "error": "LOGIN_REQUIRED",
                                "profile_ids": ["bad-login"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = type("Service", (), {"storage": Storage(), "base_dir": tmp})()
            logs = []
            app._log = logs.append

            with patch.dict(os.environ, {"REACHOPS_FORCE_ACCOUNT_RECHECK": "1"}, clear=False):
                selected = app._rank_profile_candidates(
                    [
                        {"profile_id": "bad-login", "group_name": "United States"},
                        {"profile_id": "new-account", "group_name": "United States"},
                    ],
                    2,
                )

        self.assertEqual([row["profile_id"] for row in selected], ["new-account"])
        self.assertTrue(any("force_account_recheck" in row for row in logs))
        self.assertTrue(any("recent_unusable_excluded count=1" in row for row in logs))

    def test_profile_group_display_keeps_operator_readable_group_name(self):
        display = group_display_name({"group_id": "281726", "group_name": "加拿大获客组", "count": 12})

        self.assertEqual(display, "加拿大获客组 · 12 个账号 · ID: 281726")
        self.assertEqual(stable_combobox_values([display]), [display])
        self.assertEqual(group_name_from_display(display), "加拿大获客组")
        self.assertEqual(group_name_from_display("待读取账号数 | 加拿大获客组 | ID 281726"), "加拿大获客组")
        self.assertEqual(group_name_from_display("[    3] Canada (ID: 281726)"), "Canada")
        self.assertEqual(console_safe_tk_option(display), display)
        self.assertEqual(console_group_name_from_display(display), "加拿大获客组")
        self.assertEqual(console_group_name_from_display("[    3] Canada (ID: 281726)"), "Canada")

    def test_refresh_profile_groups_uses_memory_cache_when_api_returns_empty_groups(self):
        class Value:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Console:
            def __init__(self):
                self.options = []
                self.selected = ""
                self.scan_profile_group_var = Value("")
                self.action_execution_group_var = Value("")

            def set_profile_group_options(self, options, selected):
                self.options = list(options)
                self.selected = selected

            def refresh(self, _snapshot):
                return None

        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app.profile_registry = type(
            "Registry",
            (),
            {
                "groups": [{"group_id": "257999", "group_name": "United States", "count": 240, "count_known": True}],
                "profiles": [],
            },
        )()
        app.profile_group_display_map = {}
        app.group_var = Value("")
        app.console = Console()
        app.refresh_groups_button = None
        app._group_count_refresh_in_progress = False
        app._selected_group_name = lambda: ""
        app._current_snapshot = lambda: {}
        app._resolve_profile_group_counts_async = lambda _snapshot: None
        logs = []
        app._log = logs.append

        app._apply_profile_group_snapshot(
            {"profiles": [], "groups": [], "profile_count": 0, "group_count": 0, "profiles_deferred": True},
            show_message=True,
        )

        self.assertEqual(app.console.scan_profile_group_var.get(), "United States")
        self.assertTrue(any("using_cached=1" in row for row in logs))
        self.assertTrue(any("United States" in option for option in app.console.options))

    def test_refresh_profile_groups_uses_storage_cache_and_logs_error_when_api_fails(self):
        class Value:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Console:
            def __init__(self):
                self.options = []
                self.selected = ""
                self.scan_profile_group_var = Value("")
                self.action_execution_group_var = Value("")

            def set_profile_group_options(self, options, selected):
                self.options = list(options)
                self.selected = selected

            def refresh(self, _snapshot):
                return None

        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app.profile_registry = type("Registry", (), {"groups": [], "profiles": []})()
        app.profile_group_display_map = {}
        app.group_var = Value("")
        app.console = Console()
        app.refresh_groups_button = None
        app._group_count_refresh_in_progress = False
        app._selected_group_name = lambda: ""
        app._current_snapshot = lambda: {}
        app._resolve_profile_group_counts_async = lambda _snapshot: None
        app._cached_profile_groups_from_storage = lambda: [
            {"group_id": "", "group_name": "United States", "count": 2, "count_known": True}
        ]
        logs = []
        app._log = logs.append

        app._apply_profile_group_snapshot(
            {"profiles": [], "groups": [], "profile_count": 0, "group_count": 0, "profiles_deferred": True, "error": "api down"},
            show_message=True,
        )

        self.assertEqual(app.console.action_execution_group_var.get(), "United States")
        self.assertTrue(any("using_storage_cache=1" in row for row in logs))
        self.assertTrue(any("ERROR  refresh_profiles failed error=api down" in row for row in logs))
        self.assertTrue(any("no_popup=true" in row for row in logs))

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
                        "session_retained": True,
                        "close_action": "preflight_ok_retained",
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
        self.assertTrue(any("profile=ok-1" in row and "close_action=preflight_ok_retained" in row for row in logs))
        self.assertTrue(any("profile=ok-1" in row and "已保留并交接给后续任务" in row for row in logs))
        self.assertTrue(any("profile=bad-login" in row and "error=LOGIN_REQUIRED" in row for row in logs))
        self.assertTrue(any("evidence=evidence://login" in row for row in logs))

    def test_standalone_quick_direct_target_skips_broad_source_expansion(self):
        logs = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append

        scoped = app._scope_quick_direct_target_sources(
            [
                {"source_type": "content_url", "source_value": "https://www.tiktok.com/@a/video/1"},
                {"source_type": "keyword", "source_value": "best product"},
                {"source_type": "hashtag", "source_value": "shopping"},
            ],
            detected_type="content_url",
            quick_volume_label="快速",
        )

        self.assertEqual(scoped, [{"source_type": "content_url", "source_value": "https://www.tiktok.com/@a/video/1"}])
        self.assertTrue(any("quick_direct_scope" in row and "original_sources=3" in row for row in logs))

    def test_standalone_quick_direct_target_limits_campaign_plan_sources(self):
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)

        self.assertEqual(
            app._quick_direct_target_plan_source_limit(
                "https://www.tiktok.com/@a/video/1",
                source_type="auto",
                quick_volume_label="快速",
            ),
            1,
        )
        self.assertEqual(
            app._quick_direct_target_plan_source_limit(
                "portable blender",
                source_type="auto",
                quick_volume_label="快速",
            ),
            100,
        )

    def test_standalone_profile_preflight_can_check_wide_initial_batch(self):
        class Checker:
            def available_profiles(self, profiles):
                rows = list(profiles or [])
                available = rows[:3]
                return available, {
                    "checked": len(rows),
                    "available": len(available),
                    "unavailable": max(0, len(rows) - len(available)),
                    "errors": {"LOGIN_REQUIRED": max(0, len(rows) - len(available))},
                    "results": [
                        {
                            "profile_id": str(row.get("profile_id") or ""),
                            "ok": row in available,
                            "error_code": "" if row in available else "LOGIN_REQUIRED",
                        }
                        for row in rows
                    ],
                }

        logs = []
        batch_sizes = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()

        def checker_factory(batch_size):
            batch_sizes.append(batch_size)
            return Checker()

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(6)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            checker_factory,
            stage="collection",
            min_required_profiles=3,
            max_checked_profiles=6,
            initial_check_limit=6,
        )

        self.assertEqual(batch_sizes, [6])
        self.assertEqual([row["profile_id"] for row in available], ["p0", "p1", "p2"])
        self.assertEqual(summary["checked"], 6)
        self.assertTrue(any("reason=initial profiles=6" in row for row in logs))

    def test_standalone_profile_preflight_backfills_to_requested_queue_target(self):
        class Checker:
            def __init__(self):
                self.calls = 0

            def available_profiles(self, profiles):
                self.calls += 1
                rows = list(profiles or [])
                available = rows[:1]
                return available, {
                    "checked": len(rows),
                    "available": len(available),
                    "unavailable": max(0, len(rows) - len(available)),
                    "errors": {"LOGIN_REQUIRED": max(0, len(rows) - len(available))},
                    "results": [
                        {
                            "profile_id": str(row.get("profile_id") or ""),
                            "ok": row in available,
                            "error_code": "" if row in available else "LOGIN_REQUIRED",
                        }
                        for row in rows
                    ],
                }

        logs = []
        checker = Checker()
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
        app._rank_profile_candidates = lambda profiles, _limit: list(profiles)
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "")

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(6)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            lambda _batch_size: checker,
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=6,
            initial_check_limit=1,
        )

        self.assertEqual([row["profile_id"] for row in available], ["p0", "p1", "p5"])
        self.assertEqual(summary["available"], 3)
        self.assertGreaterEqual(checker.calls, 2)
        self.assertTrue(any("backfill_start" in row for row in logs))

    def test_standalone_collection_preflight_starts_after_minimum_available_profile(self):
        class Checker:
            def __init__(self):
                self.calls = 0

            def available_profiles(self, profiles):
                self.calls += 1
                rows = list(profiles or [])
                available = rows[:1]
                return available, {
                    "checked": len(rows),
                    "available": len(available),
                    "unavailable": max(0, len(rows) - len(available)),
                    "errors": {"LOGIN_REQUIRED": max(0, len(rows) - len(available))},
                    "results": [
                        {
                            "profile_id": str(row.get("profile_id") or ""),
                            "ok": row in available,
                            "error_code": "" if row in available else "LOGIN_REQUIRED",
                        }
                        for row in rows
                    ],
                }

        logs = []
        checker = Checker()
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
        app._rank_profile_candidates = lambda profiles, _limit: list(profiles)
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "")

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(6)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            lambda _batch_size: checker,
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=6,
            initial_check_limit=3,
            backfill_to_requested=False,
        )

        self.assertEqual([row["profile_id"] for row in available], ["p0"])
        self.assertEqual(summary["available"], 1)
        self.assertEqual(checker.calls, 1)
        self.assertTrue(any("fast_start" in row for row in logs))
        self.assertFalse(any("backfill_start" in row for row in logs))

    def test_standalone_profile_preflight_circuit_breaks_ixbrowser_api_outage(self):
        class NetworkErrorChecker:
            def __init__(self, bucket):
                self.bucket = bucket

            def available_profiles(self, profiles):
                rows = list(profiles or [])
                self.bucket.append([str(row.get("profile_id") or "") for row in rows])
                return [], {
                    "checked": len(rows),
                    "available": 0,
                    "unavailable": len(rows),
                    "errors": {"IXBROWSER_NETWORK_ERROR": len(rows)},
                    "results": [
                        {
                            "profile_id": str(row.get("profile_id") or ""),
                            "ok": False,
                            "error_code": "IXBROWSER_NETWORK_ERROR",
                        }
                        for row in rows
                    ],
                }

        logs = []
        initial_batches = []
        recovery_batches = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
        app._rank_profile_candidates = lambda profiles, _limit: list(profiles)
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "")

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(10)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            lambda _batch_size: NetworkErrorChecker(initial_batches),
            recovery_checker_factory=lambda _batch_size: NetworkErrorChecker(recovery_batches),
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=10,
            initial_check_limit=3,
        )

        self.assertEqual(available, [])
        self.assertEqual(summary["checked"], 6)
        self.assertEqual([len(batch) for batch in initial_batches], [3])
        self.assertEqual([len(batch) for batch in recovery_batches], [3])
        self.assertTrue(any("circuit_breaker" in row and "stop_backfill_to_avoid_profile_start_waste" in row for row in logs))
        self.assertFalse(any("backfill_batch" in row for row in logs))

    def test_standalone_profile_preflight_does_not_retry_page_timeouts_in_same_round(self):
        class TimeoutChecker:
            def __init__(self, bucket):
                self.bucket = bucket

            def available_profiles(self, profiles):
                rows = list(profiles or [])
                self.bucket.append([str(row.get("profile_id") or "") for row in rows])
                return [], {
                    "checked": len(rows),
                    "available": 0,
                    "unavailable": len(rows),
                    "errors": {"PAGE_OPEN_FAILED": len(rows)},
                    "results": [
                        {
                            "profile_id": str(row.get("profile_id") or ""),
                            "ok": False,
                            "error_code": "PAGE_OPEN_FAILED",
                        }
                        for row in rows
                    ],
                }

        logs = []
        initial_batches = []
        recovery_batches = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
        app._rank_profile_candidates = lambda profiles, _limit: list(profiles)
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "")

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(6)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            lambda _batch_size: TimeoutChecker(initial_batches),
            recovery_checker_factory=lambda _batch_size: TimeoutChecker(recovery_batches),
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=6,
            initial_check_limit=3,
        )

        self.assertEqual(available, [])
        self.assertEqual(summary["checked"], 6)
        self.assertEqual([len(batch) for batch in initial_batches], [3, 3])
        self.assertEqual(recovery_batches, [])
        self.assertTrue(any("recovery_retry_skipped" in row and "avoid_duplicate_profile_starts" in row for row in logs))

    def test_standalone_profile_preflight_continues_after_mixed_login_and_browser_failures(self):
        class MixedChecker:
            def __init__(self, bucket):
                self.bucket = bucket

            def available_profiles(self, profiles):
                rows = list(profiles or [])
                self.bucket.append([str(row.get("profile_id") or "") for row in rows])
                checked_so_far = sum(len(batch) for batch in self.bucket[:-1])
                results = []
                available = []
                errors = {}
                for index, row in enumerate(rows):
                    profile_id = str(row.get("profile_id") or "")
                    absolute_index = checked_so_far + index
                    if absolute_index == 6:
                        available.append(row)
                        results.append({"profile_id": profile_id, "ok": True, "error_code": ""})
                        continue
                    if absolute_index in {0, 1}:
                        code = "LOGIN_REQUIRED"
                    elif absolute_index in {2, 4, 5}:
                        code = "PROFILE_PREFLIGHT_TIMEOUT"
                    else:
                        code = "PAGE_OPEN_FAILED"
                    errors[code] = errors.get(code, 0) + 1
                    results.append({"profile_id": profile_id, "ok": False, "error_code": code})
                return available, {
                    "checked": len(rows),
                    "available": len(available),
                    "unavailable": len(rows) - len(available),
                    "errors": errors,
                    "results": results,
                }

        logs = []
        batches = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
        app._rank_profile_candidates = lambda profiles, _limit: list(profiles)
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "")

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(12)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            lambda _batch_size: MixedChecker(batches),
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=12,
            initial_check_limit=3,
            backfill_to_requested=False,
        )

        self.assertEqual([row["profile_id"] for row in available], ["p6"])
        self.assertEqual(summary["checked"], 9)
        self.assertEqual([len(batch) for batch in batches], [3, 3, 3])
        self.assertTrue(any("continue_after_mixed_failures" in row for row in logs))
        self.assertFalse(any("reason=browser_start_instability" in row for row in logs))

    def test_standalone_profile_preflight_circuit_breaks_permanent_account_configuration_block(self):
        class KernelMismatchChecker:
            def __init__(self, bucket):
                self.bucket = bucket

            def available_profiles(self, profiles):
                rows = list(profiles or [])
                self.bucket.append([str(row.get("profile_id") or "") for row in rows])
                return [], {
                    "checked": len(rows),
                    "available": 0,
                    "unavailable": len(rows),
                    "errors": {"IXBROWSER_KERNEL_MISMATCH": len(rows)},
                    "results": [
                        {
                            "profile_id": str(row.get("profile_id") or ""),
                            "ok": False,
                            "error_code": "IXBROWSER_KERNEL_MISMATCH",
                        }
                        for row in rows
                    ],
                }

        logs = []
        batches = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
        app._rank_profile_candidates = lambda profiles, _limit: list(profiles)
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "")

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(20)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            lambda _batch_size: KernelMismatchChecker(batches),
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=20,
            initial_check_limit=3,
        )

        self.assertEqual(available, [])
        self.assertEqual(summary["checked"], 9)
        self.assertEqual([len(batch) for batch in batches], [3, 6])
        self.assertTrue(any("reason=permanent_account_configuration_block" in row for row in logs))
        self.assertTrue(any("stop_backfill_to_avoid_profile_start_waste" in row for row in logs))
        self.assertTrue(any("backfill_batch" in row for row in logs))

    def test_standalone_profile_preflight_circuit_breaks_when_all_candidates_hard_blocked(self):
        class KernelMismatchChecker:
            def __init__(self, bucket):
                self.bucket = bucket

            def available_profiles(self, profiles):
                rows = list(profiles or [])
                self.bucket.append([str(row.get("profile_id") or "") for row in rows])
                return [], {
                    "checked": len(rows),
                    "available": 0,
                    "unavailable": len(rows),
                    "errors": {"IXBROWSER_KERNEL_MISMATCH": len(rows)},
                    "results": [
                        {
                            "profile_id": str(row.get("profile_id") or ""),
                            "ok": False,
                            "error_code": "IXBROWSER_KERNEL_MISMATCH",
                        }
                        for row in rows
                    ],
                }

        logs = []
        batches = []
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        app._thread_log = logs.append
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app.profile_registry = type("Registry", (), {"select_profiles": lambda *_args, **_kwargs: []})()
        app._rank_profile_candidates = lambda profiles, _limit: list(profiles)
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "")

        profiles = [{"profile_id": f"p{index}", "group_name": "US"} for index in range(3)]
        available, summary = app._preflight_profiles_with_backfill(
            profiles,
            "US",
            3,
            lambda _batch_size: KernelMismatchChecker(batches),
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=20,
            initial_check_limit=3,
        )

        self.assertEqual(available, [])
        self.assertEqual(summary["checked"], 3)
        self.assertEqual([len(batch) for batch in batches], [3])
        self.assertTrue(any("reason=permanent_account_configuration_block" in row for row in logs))

    def test_standalone_cached_profiles_from_storage_filters_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.storage.record_profile_health("us-1", group_name="United States", ok=True)
            service.storage.record_profile_health("us-2", group_name="United States", ok=True)
            service.storage.record_profile_health("br-1", group_name="Brazil", ok=True)
            service.storage.log_event("profile_preflight_checked", "us-1", {"profile_id": "us-1", "ok": True})
            service.storage.log_event("profile_preflight_checked", "us-2", {"profile_id": "us-2", "ok": True})
            service.storage.log_event("profile_preflight_checked", "br-1", {"profile_id": "br-1", "ok": True})

            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service

            profiles = app._cached_profiles_from_storage("United States", limit=10)

        self.assertEqual({row["profile_id"] for row in profiles}, {"us-1", "us-2"})
        self.assertTrue(all(row["group_name"] == "United States" for row in profiles))

    def test_standalone_cached_profiles_from_storage_requires_fresh_preflight_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.storage.record_profile_health("old-ok", group_name="United States", ok=True)
            service.storage.record_profile_health("fresh-ok", group_name="United States", ok=True)
            service.storage.log_event("profile_preflight_checked", "fresh-ok", {"profile_id": "fresh-ok", "ok": True})

            with service.storage.connect() as conn:
                conn.execute(
                    "INSERT INTO growth_events (id, event, entity_id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        "evt_old_preflight",
                        "profile_preflight_checked",
                        "old-ok",
                        json.dumps({"profile_id": "old-ok", "ok": True}),
                        "2020-01-01T00:00:00Z",
                    ),
                )

            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service

            profiles = app._cached_profiles_from_storage("United States", limit=10)

        self.assertEqual([row["profile_id"] for row in profiles], ["fresh-ok"])

    def test_standalone_cached_profiles_excludes_recent_runtime_browser_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            service.storage.record_profile_health("crashed-ok", group_name="United States", ok=True)
            service.storage.record_profile_health("fresh-ok", group_name="United States", ok=True)
            service.storage.log_event("profile_preflight_checked", "crashed-ok", {"profile_id": "crashed-ok", "ok": True})
            service.storage.log_event("profile_preflight_checked", "fresh-ok", {"profile_id": "fresh-ok", "ok": True})
            service.storage.log_error(
                "BROWSER_CRASHED",
                "chrome not reachable",
                profile_id="crashed-ok",
            )

            app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
            app.service = service

            profiles = app._cached_profiles_from_storage("United States", limit=10)

        self.assertEqual([row["profile_id"] for row in profiles], ["fresh-ok"])

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
                    "executions_csv_path": "/tmp/executions.csv",
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

    def test_standalone_logs_collection_done_without_waiting_for_tk_callback(self):
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        logs = []
        app._log = logs.append

        result = type(
            "Result",
            (),
            {
                "processed_sources": 2,
                "report_json_path": "/tmp/report.json",
                "report_csv_path": "/tmp/report.csv",
                "errors": {"EMPTY_RESULT_RETRY": 1},
            },
        )()

        app._log_collection_finished(result)

        self.assertTrue(any("DONE   collection processed_sources=2" in row for row in logs))
        self.assertTrue(any("errors=EMPTY_RESULT_RETRY=1" in row for row in logs))
        self.assertTrue(any("recoverable_errors=EMPTY_RESULT_RETRY=1" in row and "no_popup=true" in row for row in logs))

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

    def test_ixbrowser_profile_loader_matches_smart_publish_by_omitting_group_id_for_all_profiles(self):
        import sys
        import types

        class FakeIXBrowserClient:
            calls = []

            def __init__(self):
                self.total = 2

            def get_profile_list(self, page=1, limit=100, **kwargs):
                self.calls.append({"page": page, "limit": limit, **kwargs})
                if "group_id" in kwargs:
                    return []
                if page == 1:
                    return [
                        {"profile_id": "ca-1", "group_id": "281726", "group_name": "Canada"},
                        {"profile_id": "br-1", "group_id": "286343", "group_name": "BR"},
                    ]
                return []

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import load_ixbrowser_profile_rows

            rows = load_ixbrowser_profile_rows(max_pages=3)

        self.assertEqual([str(row["profile_id"]) for row in rows], ["ca-1", "br-1"])
        self.assertTrue(FakeIXBrowserClient.calls)
        self.assertTrue(all("group_id" not in call for call in FakeIXBrowserClient.calls))

    def test_profile_registry_selects_profiles_by_group_id_from_refreshed_catalog(self):
        from ReachOps.workbench.standalone_app import StandaloneProfileRegistry

        registry = StandaloneProfileRegistry()
        registry.profiles = [
            {"profile_id": "ca-1", "group_id": "281726", "group_name": "Canada"},
            {"profile_id": "ca-2", "group_id": "281726", "group_name": "Canada"},
            {"profile_id": "br-1", "group_id": "286343", "group_name": "BR"},
        ]
        registry.groups = [{"group_id": "281726", "group_name": "Canada", "count": 0}]
        registry.group_by_name = {"Canada": registry.groups[0]}

        with patch(
            "ReachOps.workbench.standalone_app.load_ixbrowser_profile_rows",
            side_effect=AssertionError("select_profiles should use refreshed profile catalog"),
        ) as loader:
            rows = registry.select_profiles("Canada", limit=10)

        loader.assert_not_called()
        self.assertEqual([row["profile_id"] for row in rows], ["ca-1", "ca-2"])

    def test_ixbrowser_group_profile_count_pages_without_total(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def get_profile_list(self, page=1, limit=100, group_id=0, **_kwargs):
                self.total = 0
                if str(group_id) != "281726":
                    return []
                pages = {
                    1: [{"profile_id": "ca-1", "group_id": "281726", "group_name": "Canada"}],
                    2: [{"profile_id": "ca-2", "group_id": "281726", "group_name": "Canada"}],
                    3: [],
                    4: [],
                    5: [],
                }
                return pages.get(page, [])

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import load_ixbrowser_group_profile_count

            count = load_ixbrowser_group_profile_count("281726", max_pages=5, limit=1)

        self.assertEqual(count, 2)

    def test_ixbrowser_group_counts_resolve_from_full_profile_list(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def get_profile_list(self, page=1, limit=100, **_kwargs):
                self.total = 5
                if page == 1:
                    return {
                        "data": {
                            "records": [
                                {"profileId": "ca-1", "groupId": "281726", "groupName": "Canada"},
                                {"profileId": "ca-2", "groupId": "281726", "groupName": "Canada"},
                                {"profileId": "us-1", "groupId": "257999", "groupName": "United States"},
                                {"profileId": "tw-1", "groupId": "300001", "groupName": "台湾国学"},
                                {"profileId": "tw-2", "groupId": "300001", "groupName": "台湾国学"},
                            ],
                            "totalCount": 5,
                        }
                    }
                return {"data": {"records": [], "totalCount": 5}}

        groups = [
            {"group_id": "281726", "group_name": "Canada", "count": 0, "count_known": False},
            {"group_id": "257999", "group_name": "United States", "count": 0, "count_known": False},
            {"group_id": "300001", "group_name": "台湾国学", "count": 0, "count_known": False},
        ]
        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import resolve_ixbrowser_group_counts

            resolved = resolve_ixbrowser_group_counts(groups, timeout_seconds=2)

        counts = {row["group_name"]: row["count"] for row in resolved}
        self.assertEqual(counts, {"Canada": 2, "United States": 1, "台湾国学": 2})
        self.assertTrue(all(row["count_known"] for row in resolved))

    def test_ixbrowser_metadata_report_exposes_all_group_count_evidence(self):
        class FakeIXBrowserClient:
            def get_group_list(self, page=1, limit=100):
                if page != 1:
                    return {"data": {"records": [], "totalCount": 2}}
                return {
                    "data": {
                        "records": [
                            {"id": "281726", "title": "Canada"},
                            {"id": "257999", "title": "United States"},
                        ],
                        "totalCount": 2,
                    }
                }

            def get_profile_list(self, page=1, limit=100, group_id=0, **_kwargs):
                if str(group_id) == "257999":
                    return {
                        "data": {
                            "records": [
                                {"profile_id": "us-1", "group_id": "257999", "group_name": "United States"},
                                {"profile_id": "us-2", "group_id": "257999", "group_name": "United States"},
                            ],
                            "totalCount": 2,
                        }
                    }
                return {"data": {"records": [], "totalCount": 0}}

            def get_proxy_list(self, page=1, limit=100, **_kwargs):
                return {"data": {"records": [], "totalCount": 0}}

        def fake_resolve(groups, **_kwargs):
            for row in groups:
                if row["group_name"] == "Canada":
                    row["count"] = 3
                    row["count_known"] = True
                if row["group_name"] == "United States":
                    row["count"] = 2
                    row["count_known"] = True
            return groups

        with patch("ReachOps.workbench.standalone_app.resolve_ixbrowser_group_counts", side_effect=fake_resolve), patch(
            "ReachOps.workbench.standalone_app.load_ixbrowser_group_profile_count",
            return_value=2,
        ):
            payload = build_ixbrowser_profile_metadata_report(
                client=FakeIXBrowserClient(),
                group_name="United States",
                max_pages=2,
                profile_limit=20,
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["group_count"], 2)
        self.assertEqual(payload["known_group_count"], 2)
        self.assertTrue(payload["all_group_counts_known"])
        self.assertEqual(payload["profile_count"], 5)
        self.assertEqual(payload["selected_profile_count"], 2)
        self.assertEqual(payload["selected_group_id"], "257999")

    def test_ixbrowser_list_none_response_is_reported_as_local_api_error(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def __init__(self, target="127.0.0.1", port=53200):
                self.base_url = f"http://{target}:{port}/api/v2/"
                self.code = 1
                self.message = "connection refused"

            def get_group_list(self, page=1, limit=100):
                return None

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import load_ixbrowser_group_rows

            with self.assertRaisesRegex(RuntimeError, "ixbrowser_group_list_unavailable"):
                load_ixbrowser_group_rows(max_pages=1, limit=10)

    def test_web_group_refresh_normalizes_ixbrowser_local_api_connection_error(self):
        from tools import reachops_web_ui

        with tempfile.TemporaryDirectory() as tmp:
            old_cache = dict(reachops_web_ui.GROUP_CACHE)
            old_path = reachops_web_ui.LATEST_GROUPS_PATH
            try:
                reachops_web_ui.GROUP_CACHE = {"loaded_at": 0.0, "groups": [], "error": ""}
                reachops_web_ui.LATEST_GROUPS_PATH = Path(tmp) / "missing_latest_groups.json"
                with patch(
                    "ReachOps.workbench.standalone_app.StandaloneProfileRegistry.refresh",
                    side_effect=RuntimeError(
                        "ixbrowser_group_list_unavailable base_url=http://127.0.0.1:53200/api/v2/ "
                        "code=1 message=exception desc: Failed to establish a new connection: [Errno 61] Connection refused"
                    ),
                ):
                    payload = reachops_web_ui.load_groups(refresh=True)
            finally:
                reachops_web_ui.GROUP_CACHE = old_cache
                reachops_web_ui.LATEST_GROUPS_PATH = old_path

        self.assertEqual(payload["groups"], [])
        self.assertEqual(payload["error"], "ixBrowser Local API 未启动或端口不可连接")
        self.assertIn("ixbrowser_group_list_unavailable", payload["error_detail"])

    def test_web_group_refresh_failure_keeps_last_successful_group_counts(self):
        from tools import reachops_web_ui

        with tempfile.TemporaryDirectory() as tmp:
            latest_path = Path(tmp) / "latest_ixbrowser_groups.json"
            latest_payload = {
                "loaded_at": 1,
                "groups": [
                    {
                        "label": "United States / 717账号",
                        "name": "United States",
                        "group_id": "257999",
                        "count": 717,
                        "count_known": True,
                        "count_label": "717账号",
                        "count_status": "known",
                    }
                ],
                "group_count": 1,
                "known_group_count": 1,
                "counts_resolved": True,
            }
            latest_path.write_text(json.dumps(latest_payload, ensure_ascii=False), encoding="utf-8")
            old_cache = dict(reachops_web_ui.GROUP_CACHE)
            old_path = reachops_web_ui.LATEST_GROUPS_PATH
            try:
                reachops_web_ui.GROUP_CACHE = {"loaded_at": 0.0, "groups": [], "error": ""}
                reachops_web_ui.LATEST_GROUPS_PATH = latest_path
                with patch(
                    "ReachOps.workbench.standalone_app.StandaloneProfileRegistry.refresh",
                    side_effect=RuntimeError(
                        "ixbrowser_group_list_unavailable base_url=http://127.0.0.1:53200/api/v2/ "
                        "code=1008 message=Server busy, please try again later."
                    ),
                ):
                    payload = reachops_web_ui.load_groups(refresh=True)
            finally:
                reachops_web_ui.GROUP_CACHE = old_cache
                reachops_web_ui.LATEST_GROUPS_PATH = old_path

            self.assertEqual(payload["groups"][0]["name"], "United States")
            self.assertEqual(payload["groups"][0]["count"], 717)
            self.assertTrue(payload["stale_cache"])
            self.assertEqual(payload["error"], "ixBrowser Local API 繁忙，请稍后重试")
            persisted = json.loads(latest_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["groups"][0]["count"], 717)

    def test_ixbrowser_adapter_closes_profile_when_driver_import_fails(self):
        import builtins
        import sys
        import types

        from ReachOps.adapters.browser_manager import IxBrowserLocalAdapter

        class FakeIXBrowserClient:
            closed = []

            def open_profile(self, profile_id, **_kwargs):
                return {"webdriver": "C:\\fake\\chromedriver.exe", "debugging_port": 9222}

            def close_profile(self, profile_id):
                self.closed.append(str(profile_id))

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "selenium" or name.startswith("selenium."):
                raise ModuleNotFoundError("No module named 'selenium.webdriver.chrome.webdriver'")
            return original_import(name, *args, **kwargs)

        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}), patch("builtins.__import__", side_effect=fake_import):
            driver, client = IxBrowserLocalAdapter().create_driver("22315")

        self.assertIsNone(driver)
        self.assertIsNone(client)
        self.assertEqual(FakeIXBrowserClient.closed, ["22315"])

    def test_profile_registry_refresh_resolves_group_counts(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def get_group_list(self, page=1, limit=100):
                if page == 1:
                    return []
                return []

            def get_profile_list(self, page=1, limit=100, group_id=0, **_kwargs):
                self.total = 0
                if int(group_id or 0) == 0:
                    pages = {
                        1: [
                            {"profile_id": "ca-1", "group_id": "281726", "group_name": "Canada"},
                            {"profile_id": "ca-2", "group_id": "281726", "group_name": "Canada"},
                            {"profile_id": "br-1", "group_id": "286343", "group_name": "BR"},
                        ],
                        2: [],
                        3: [],
                        4: [],
                    }
                    return pages.get(page, [])
                return []

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import StandaloneProfileRegistry

            registry = StandaloneProfileRegistry()
            snapshot = registry.refresh(max_pages=3, include_profiles=True)

        counts = {row["group_name"]: row["count"] for row in snapshot["groups"]}
        self.assertEqual(counts, {"全部配置": 3, "BR": 1, "Canada": 2})
        self.assertIn("2 个账号", group_display_name(next(row for row in snapshot["groups"] if row["group_name"] == "Canada")))
        self.assertEqual([row["profile_id"] for row in registry.select_profiles("Canada", limit=10)], ["ca-1", "ca-2"])

    def test_ixbrowser_group_loader_pages_all_groups_until_total(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def __init__(self):
                self.total = 0

            def get_group_list(self, page=1, limit=100):
                self.total = 3
                pages = {
                    1: [{"id": "g1", "title": "BR"}],
                    2: [],
                    3: [{"id": "g2", "title": "Canada"}],
                    4: [{"id": "g3", "title": "US"}],
                }
                return pages.get(page, [])

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import load_ixbrowser_group_rows

            rows = load_ixbrowser_group_rows(max_pages=10, limit=1)

        self.assertEqual([str(row["id"]) for row in rows], ["g1", "g2", "g3"])

    def test_ixbrowser_group_loader_accepts_wrapped_api_response(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def __init__(self):
                self.total = 0

            def get_group_list(self, page=1, limit=100):
                pages = {
                    1: {
                        "data": {
                            "list": [
                                {"groupId": "281726", "groupName": "Canada", "profileCount": 2},
                                {"groupId": "257999", "groupName": "United States", "profileCount": 3},
                            ],
                            "total": 3,
                        }
                    },
                    2: {"data": {"list": [{"groupId": "286343", "groupName": "BR", "profileCount": 1}], "total": 3}},
                }
                return pages.get(page, {"data": {"list": [], "total": 3}})

            def get_profile_list(self, page=1, limit=100, group_id=0, **_kwargs):
                return {"data": {"list": [], "total": 0}}

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import load_ixbrowser_profile_snapshot

            snapshot = load_ixbrowser_profile_snapshot(resolve_group_counts=False, include_profiles=False)

        self.assertEqual(snapshot["group_count"], 3)
        self.assertEqual([row["group_name"] for row in snapshot["groups"]], ["BR", "Canada", "United States"])
        self.assertEqual({row["group_name"]: row["count"] for row in snapshot["groups"]}, {"Canada": 2, "United States": 3, "BR": 1})

    def test_ixbrowser_profile_loader_accepts_wrapped_api_response(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def get_profile_list(self, page=1, limit=100, group_id=0, **_kwargs):
                if page == 1:
                    return {
                        "data": {
                            "records": [
                                {"profileId": "ca-1", "profileName": "CA 1", "groupId": "281726", "groupName": "Canada"},
                                {"profileId": "ca-2", "profileName": "CA 2", "groupId": "281726", "groupName": "Canada"},
                            ],
                            "totalCount": 2,
                        }
                    }
                return {"data": {"records": [], "totalCount": 2}}

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import load_ixbrowser_profile_rows

            rows = load_ixbrowser_profile_rows(max_pages=3, group_id=281726)

        self.assertEqual([row["profileId"] for row in rows], ["ca-1", "ca-2"])

    def test_profile_registry_refresh_builds_groups_from_full_profile_list(self):
        import sys
        import types

        class FakeIXBrowserClient:
            def __init__(self):
                self.total = 0

            def get_group_list(self, page=1, limit=100):
                self.total = 1
                if page == 1:
                    return [{"id": "stale", "title": "Stale Group", "count": 999}]
                return []

            def get_profile_list(self, page=1, limit=100, group_id=0, **_kwargs):
                self.total = 3
                if int(group_id or 0) == 0 and page == 1:
                    return [
                        {"profile_id": "ca-1", "group_id": "281726", "group_name": "Canada"},
                        {"profile_id": "ca-2", "group_id": "281726", "group_name": "Canada"},
                        {"profile_id": "us-1", "group_id": "257999", "group_name": "United States"},
                    ]
                return []

        fake_module = types.SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
        with patch.dict(sys.modules, {"ixbrowser_local_api": fake_module}):
            from ReachOps.workbench.standalone_app import StandaloneProfileRegistry

            registry = StandaloneProfileRegistry()
            snapshot = registry.refresh(max_pages=5, include_profiles=True)

        counts = {row["group_name"]: row["count"] for row in snapshot["groups"]}
        self.assertEqual(counts, {"全部配置": 3, "Canada": 2, "United States": 1})
        self.assertNotIn("Stale Group", counts)
        labels = {row["group_name"]: group_display_name(row) for row in snapshot["groups"]}
        self.assertIn("2 个账号", labels["Canada"])
        self.assertIn("3 个账号", labels["全部配置"])
        self.assertNotIn("待读取账号数", labels["Canada"])

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

    def test_comment_collector_detects_account_setup_modal_as_login_required(self):
        driver = FakeDriver()
        driver.current_url = "https://www.tiktok.com/"
        driver.title = "TikTok - Make Your Day"
        driver.script_results = [
            {
                "url": driver.current_url,
                "title": "tiktok - make your day",
                "commentNodes": 0,
                "loginPrompt": False,
                "loginPage": False,
                "accountSetupGate": True,
                "loginDialog": False,
                "captcha": False,
                "proxy": False,
                "emptyHint": False,
                "containers": 0,
            }
        ]

        diagnostics = TikTokCommentCollector()._inspect_comment_state(driver, {"max_visible_nodes": 0})

        self.assertEqual(diagnostics["error_code"], "LOGIN_REQUIRED")
        self.assertTrue(diagnostics["account_setup_gate_detected"])

    def test_preflight_backfill_reuses_cached_profiles_without_reopening_them(self):
        app = GrowthIntelligenceStandaloneApp.__new__(GrowthIntelligenceStandaloneApp)
        logs = []
        app._thread_log = logs.append
        app._profile_id = lambda profile: str(profile.get("profile_id") or profile.get("id") or "").strip()
        app._format_error_counts = lambda errors: ",".join(f"{key}={value}" for key, value in sorted((errors or {}).items()))
        app._log_profile_preflight_details = lambda *_args, **_kwargs: None
        app._rank_profile_candidates = lambda profiles, limit: list(profiles or [])[:limit]

        checked_ids = []

        class Checker:
            def __init__(self, _batch_size):
                pass

            def available_profiles(self, profiles):
                checked_ids.extend(str(row.get("profile_id")) for row in profiles)
                return list(profiles), {
                    "checked": len(profiles),
                    "available": len(profiles),
                    "unavailable": 0,
                    "errors": {},
                    "results": [
                        {"profile_id": str(row.get("profile_id")), "ok": True, "error_code": ""}
                        for row in profiles
                    ],
                }

        profiles = [
            {"profile_id": "13744", "group_name": "United States"},
            {"profile_id": "20001", "group_name": "United States"},
            {"profile_id": "20002", "group_name": "United States"},
        ]

        executable, summary = app._preflight_profiles_with_backfill(
            profiles,
            "United States",
            3,
            lambda batch_size: Checker(batch_size),
            stage="collection",
            min_required_profiles=1,
            max_checked_profiles=6,
            initial_check_limit=3,
            backfill_to_requested=True,
            prevalidated_profiles=[profiles[0]],
        )

        self.assertEqual([row["profile_id"] for row in executable], ["13744", "20001", "20002"])
        self.assertNotIn("13744", checked_ids)
        self.assertEqual(checked_ids, ["20001", "20002"])
        self.assertEqual(summary["available"], 3)
        self.assertTrue(any("cached_available" in row for row in logs))

    def test_collection_batch_total_sources_can_follow_effective_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = make_reachops_service(tmp)
            batch = service.storage.create_collection_batch(20, profile_group="United States")
            service.storage.update_collection_batch_total_sources(batch.id, 3)
            latest = service.storage.list_collection_batches(limit=1)[0]

        self.assertEqual(latest["id"], batch.id)
        self.assertEqual(latest["total_sources"], 3)


if __name__ == "__main__":
    unittest.main()

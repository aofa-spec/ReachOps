# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ReachOps.evidence_bundle import (
    build_ai_usage_summary,
    build_autonomous_execution_summary,
    build_autonomy_readiness_summary,
    build_evidence_bundle,
    build_run_session_health_summary,
    infer_observed_runtime_states_from_log,
    build_product_capability_summary,
    build_risk_policy_summary,
    render_evidence_markdown,
    write_evidence_bundle,
    write_evidence_markdown,
)
from ReachOps.execution_plan import attach_autonomous_preflight_forecast, build_execution_plan, write_execution_plan
from ReachOps.run_recovery import recover_interrupted_run_session
from ReachOps.run_session import create_run_session, transition_run_session, write_run_session
from ReachOps.workbench.offline_learning_ledger import review_policy_candidate


class EvidenceBundleTests(unittest.TestCase):
    def test_autonomous_summary_uses_runtime_log_states_when_sampling_misses_collection(self) -> None:
        plan = build_execution_plan(target="https://example.test/product", mode="preflight")
        session = create_run_session(plan)
        session = transition_run_session(session, "PRECHECK", last_stage="RUN web_headless_start")
        session = transition_run_session(session, "PROFILE_PREFLIGHT", last_stage="CHECK profile_preflight")
        session = transition_run_session(
            session,
            "EXECUTING",
            last_stage="FAST acceptance status=executed mode=preflight no_submit=true",
            result={"status": "completed"},
        )
        log_lines = [
            "RUN    web_headless_start target=https://example.test/product",
            "QUEUE  account_queue_effective batch=gb_1 requested_concurrency=3 effective_concurrency=3",
            "VIDEO  material_discovered content=sc_1 url=https://www.tiktok.com/@demo/video/1",
            "VIDEO  comment_scan_started content=ct_1 profile=18979 source=Peptide",
            "FAST   collection_result mode=preflight used_profiles=3 processed_sources=5 failed_sources=1 no_submit=true",
            "START  action_preflight batch=gb_1 actions=6 queued_total=7 no_submit=true",
            "TOUCH  success mode=action_preflight action=aq_1 type=comment_reply profile=18979",
            "FAST   acceptance status=executed mode=preflight actions=6 success=3 failed=3 skipped=0 no_submit=true error=无",
        ]

        observed = infer_observed_runtime_states_from_log(log_lines)
        summary = build_autonomous_execution_summary(
            session,
            build_run_session_health_summary(session),
            {},
            {
                "audit_status": "pass",
                "execution_phase_ai_call_count": 0,
                "execution_phase_token_estimate": 0,
            },
            log_lines,
        )

        self.assertIn("PROFILE_OPENING", observed)
        self.assertIn("COLLECTING", observed)
        self.assertIn("PROFILE_OPENING", summary["observed_states"])
        self.assertIn("COLLECTING", summary["observed_states"])
        self.assertEqual(summary["missing_core_states"], [])
        self.assertTrue(summary["autonomous_core_ready"])

    def test_bundle_summarizes_interrupted_run_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = build_execution_plan(target="interrupted serum", mode="collect", base_dir=str(base))
            plan_path = write_execution_plan(plan, base / "plans" / "plan.json")
            session = create_run_session(
                plan,
                execution_plan_path=str(plan_path),
                result_path=str(base / "result.json"),
                log_path=str(base / "runtime.log"),
            )
            session = transition_run_session(
                session,
                "COLLECTING",
                pid=1234,
                last_stage="COLLECT profile=profile-1",
                checkpoint_update={
                    "runtime_state_inferred": "COLLECTING",
                    "log_line_count": 7,
                    "last_log_line": "COLLECT profile=profile-1",
                    "terminal_seen": False,
                    "no_ai_token_used": True,
                },
            )
            session, recovery = recover_interrupted_run_session(
                session,
                running=False,
                run_result={},
                last_stage="COLLECT profile=profile-1",
            )
            session_path = write_run_session(session, base / "runs" / "run.json")
            result_path = base / "result.json"
            result_path.write_text(json.dumps(recovery["result"]), encoding="utf-8")
            log_path = base / "runtime.log"
            log_path.write_text(
                "WARN   run_session_recovered_interrupted reason=PROCESS_INTERRUPTED\n",
                encoding="utf-8",
            )

            bundle = build_evidence_bundle(
                base_dir=base,
                execution_plan_path=str(plan_path),
                run_session_path=str(session_path),
                result_path=str(result_path),
                log_path=str(log_path),
            )

            recovery_summary = bundle["run_recovery_summary"]
            self.assertEqual(recovery_summary["schema_version"], "reachops.run_recovery_summary.v1")
            self.assertTrue(recovery_summary["recovered"])
            self.assertEqual(recovery_summary["latest_reason"], "PROCESS_INTERRUPTED")
            self.assertEqual(recovery_summary["result_error"], "process_interrupted")
            self.assertEqual(recovery_summary["terminal_state"], "BLOCKED")
            self.assertEqual(recovery_summary["checkpoint_log_line_count"], 7)
            self.assertTrue(recovery_summary["no_ai_token_used"])
            self.assertTrue(bundle["audit"]["run_recovery_recovered"])
            self.assertEqual(bundle["audit"]["run_recovery_reason"], "PROCESS_INTERRUPTED")
            markdown = render_evidence_markdown(bundle)
            self.assertIn("Run Recovery Summary", markdown)
            self.assertIn("Latest reason: PROCESS_INTERRUPTED", markdown)

    def test_bundle_indexes_plan_session_result_log_and_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = build_execution_plan(target="anti aging serum", mode="collect", base_dir=str(base))
            plan = attach_autonomous_preflight_forecast(
                plan,
                preflight_decision={
                    "schema_version": "reachops.start_preflight_decision.v1",
                    "status": "ready",
                    "start_allowed": True,
                    "gate_state": "可启动",
                    "blockers": [],
                    "next_actions": ["可以启动本地执行。"],
                    "no_ai_token_used": True,
                    "no_browser_started": True,
                    "no_submit": True,
                },
            )
            plan["runtime"]["autonomous_preflight_forecast"]["repair_routes"].append(
                {
                    "state": "CAPTCHA_DETECTED",
                    "action": "capture_page_state_bundle",
                    "terminal_outcome": "blocked",
                }
            )
            plan_path = write_execution_plan(plan, base / "plans" / "plan.json")
            session = create_run_session(
                plan,
                execution_plan_path=str(plan_path),
                result_path=str(base / "result.json"),
                log_path=str(base / "runtime.log"),
            )
            session = transition_run_session(session, "PRECHECK", last_stage="RUN web_headless_start")
            session = transition_run_session(session, "PROFILE_OPENING", last_stage="headless_profile_groups_refreshed")
            session = transition_run_session(
                session,
                "COLLECTING",
                last_stage="COLLECT running",
                checkpoint_update={
                    "runtime_state_inferred": "COLLECTING",
                    "log_line_count": 3,
                    "last_log_line": "COLLECT running profile=profile-1",
                    "terminal_seen": False,
                    "no_ai_token_used": True,
                },
                control={"paused": True, "last_action": "pause", "status": "paused", "ok": True, "reason": "operator_pause"},
            )
            session = transition_run_session(
                session,
                "COMPLETED",
                last_stage="DONE collection",
                result={
                    "status": "completed",
                    "execution_plan_contract": {
                        "schema_version": "reachops.execution_plan_runtime_contract.v1",
                        "source": "execution_plan",
                        "plan_id": plan["plan_id"],
                        "plan_fingerprint_sha256": plan["plan_fingerprint_sha256"],
                        "runtime_after_fingerprint_sha256": "runtime-after",
                        "cli_args_ignored_for_plan_fields": True,
                        "before": {"target": "cli target"},
                        "after": {"target": plan["target"]},
                        "no_ai_token_used": True,
                    },
                },
                control={"paused": False, "last_action": "resume", "status": "running", "ok": True, "reason": "operator_resume"},
            )
            session_path = write_run_session(session, base / "runs" / "run.json")
            result_path = base / "result.json"
            page_state_dir = base / "page_state"
            page_state_dir.mkdir(parents=True, exist_ok=True)
            repair_evidence_path = page_state_dir / "dom_stalled.png"
            page_state_screenshot_path = page_state_dir / "captcha.png"
            page_state_sidecar_path = page_state_dir / "captcha.json"
            unknown_state_evidence_path = page_state_dir / "unknown.png"
            repair_evidence_path.write_bytes(b"dom stalled screenshot")
            page_state_screenshot_path.write_bytes(b"captcha screenshot")
            unknown_state_evidence_path.write_bytes(b"unknown state screenshot")
            page_state_sidecar_path.write_text(
                json.dumps(
                    {
                        "schema_version": "reachops.page_state.v1",
                        "page_state": {"state": "CAPTCHA_DETECTED"},
                        "screenshot": {"path": str(page_state_screenshot_path), "captured": True},
                        "sidecar_path": str(page_state_sidecar_path),
                        "no_ai_token_used": True,
                    }
                ),
                encoding="utf-8",
            )
            result_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "generated_at": "2026-07-05T00:00:00Z",
                        "execution_plan_contract": {
                            "schema_version": "reachops.execution_plan_runtime_contract.v1",
                            "source": "execution_plan",
                            "plan_id": plan["plan_id"],
                            "plan_fingerprint_sha256": plan["plan_fingerprint_sha256"],
                            "runtime_after_fingerprint_sha256": "runtime-after",
                            "cli_args_ignored_for_plan_fields": True,
                            "before": {"target": "cli target"},
                            "after": {"target": plan["target"]},
                            "no_ai_token_used": True,
                        },
                        "results": [
                            {
                                "status": "failed",
                                "error_code": "DOM_STALLED",
                                "repair_decision": {
                                    "schema_version": "reachops.repair_policy.v1",
                                    "error_code": "DOM_STALLED",
                                    "action": "retry_same_profile_with_backoff",
                                    "reason": "transient_page_or_browser_state",
                                    "retry_same_profile": True,
                                    "no_ai_token_used": True,
                                },
                                "repair_audit": {
                                    "schema_version": "reachops.repair_audit.v1",
                                    "stage": "decision",
                                    "action_id": "action-1",
                                    "action_type": "comment_reply",
                                    "profile_id": "profile-1",
                                    "attempt": 1,
                                    "status": "failed",
                                    "error_code": "DOM_STALLED",
                                    "repair_action": "retry_same_profile_with_backoff",
                                    "repair_reason": "transient_page_or_browser_state",
                                    "retry_same_profile": True,
                                    "switch_profile": False,
                                    "cooldown_profile": False,
                                    "fallback_available": False,
                                    "degrade_to": "",
                                    "block_execution": False,
                                    "retry_after_seconds": 5,
                                    "cooldown_seconds": 0,
                                    "requires_human_review": False,
                                    "evidence_bundle_required": True,
                                    "executable_steps": [{"step": "backoff", "seconds": 5}],
                                    "repair_step_results": [
                                        {"step": "backoff", "status": "executed", "seconds": 5, "no_ai_token_used": True},
                                        {"step": "refresh_page", "status": "requires_browser_executor", "no_ai_token_used": True},
                                    ],
                                    "page_state": "DOM_STALLED",
                                    "evidence_path": str(repair_evidence_path),
                                    "next_actions": ["刷新页面或重新定位目标元素。"],
                                    "no_ai_token_used": True,
                                },
                                "risk_gate": {
                                    "schema_version": "reachops.risk_gate.v1",
                                    "allowed": False,
                                    "reason_code": "LIVE_SUBMIT_NOT_AUTHORIZED",
                                    "reason": "missing authorization",
                                    "requires_authorization": True,
                                    "authorization_ok": False,
                                    "quota_ok": True,
                                    "rate_limit_ok": True,
                                    "high_risk": False,
                                    "block_execution": True,
                                    "requires_human_review": True,
                                    "risk_actions": [{"step": "request_operator_authorization", "required": True}],
                                    "no_ai_token_used": True,
                                },
                                "account_health": {
                                    "profile_id": "profile-1",
                                    "group_name": "US",
                                    "health_score": 20,
                                    "status": "cooldown",
                                    "consecutive_failures": 3,
                                    "last_error_code": "COMMENT_SUBMIT_NOT_CONFIRMED",
                                    "last_error_message": "not visible",
                                    "updated_at": "2026-07-05T00:00:00Z",
                                },
                                "page_diagnostics": {
                                    "page_state": {
                                        "schema_version": "reachops.page_state.v1",
                                        "state": "CAPTCHA_DETECTED",
                                        "current_url": "https://www.tiktok.com/verify",
                                        "title": "Verify",
                                        "body_text_sha256": "abc",
                                        "signals": ["captcha_or_verification_text"],
                                        "selector_counts": {},
                                        "no_ai_token_used": True,
                                    }
                                },
                                "page_state_bundle": {
                                    "schema_version": "reachops.page_state.v1",
                                    "page_state": {
                                        "schema_version": "reachops.page_state.v1",
                                        "state": "CAPTCHA_DETECTED",
                                        "current_url": "https://www.tiktok.com/verify",
                                        "title": "Verify",
                                        "body_text_sha256": "abc",
                                        "signals": ["captcha_or_verification_text"],
                                        "selector_counts": {},
                                        "no_ai_token_used": True,
                                    },
                                    "screenshot": {
                                        "path": str(page_state_screenshot_path),
                                        "captured": True,
                                        "size": page_state_screenshot_path.stat().st_size,
                                    },
                                    "sidecar_path": str(page_state_sidecar_path),
                                    "no_ai_token_used": True,
                                },
                            }
                            ,
                            {
                                "status": "blocked",
                                "risk_gate": {
                                    "schema_version": "reachops.risk_gate.v1",
                                    "allowed": False,
                                    "profile_id": "profile-2",
                                    "action_type": "comment_reply",
                                    "reason_code": "DAILY_QUOTA_EXCEEDED",
                                    "reason": "20/20",
                                    "requires_authorization": False,
                                    "authorization_ok": True,
                                    "quota_ok": False,
                                    "rate_limit_ok": True,
                                    "block_execution": True,
                                    "requires_human_review": False,
                                    "evidence": {"used": 20, "limit": 20},
                                    "risk_actions": [
                                        {"step": "block_execution", "required": True},
                                        {"step": "wait_or_switch_profile", "scope": "same_profile_group"},
                                    ],
                                    "no_ai_token_used": True,
                                },
                            },
                            {
                                "status": "blocked",
                                "risk_gate": {
                                    "schema_version": "reachops.risk_gate.v1",
                                    "allowed": False,
                                    "profile_id": "profile-3",
                                    "action_type": "comment_reply",
                                    "reason_code": "DUPLICATE_ACTION_TEXT",
                                    "reason": "duplicate action text",
                                    "requires_authorization": False,
                                    "authorization_ok": True,
                                    "quota_ok": True,
                                    "rate_limit_ok": True,
                                    "block_execution": True,
                                    "requires_human_review": False,
                                    "evidence": {"text_sha256": "abc", "window_seconds": 86400},
                                    "risk_actions": [
                                        {"step": "block_execution", "required": True},
                                        {"step": "rewrite_or_rotate_message", "required": True},
                                    ],
                                    "no_ai_token_used": True,
                                },
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            log_path = base / "runtime.log"
            log_path.write_text(
                "PLAN   campaign target=anti aging serum\n"
                "action_router_repair_decision error_code=DOM_STALLED action=retry_same_profile_with_backoff\n"
                "profile_forced_cooldown profile=profile-1 status=cooldown error_code=COMMENT_SUBMIT_NOT_CONFIRMED reason=consecutive_failures\n"
                "DONE   collection completed\n",
                encoding="utf-8",
            )
            offline_path = base / "offline_learning" / "unknown_states.json"
            offline_path.parent.mkdir(parents=True, exist_ok=True)
            offline_path.write_text(
                json.dumps(
                    {
                        "schema_version": "reachops.offline_learning.v1",
                        "records": {
                            "uls_test": {
                                "signature": "uls_test",
                                "state": "UNKNOWN_PAGE_STATE",
                                "occurrence_count": 2,
                                "suggested_policy": {
                                    "candidate_state": "CAPTCHA_DETECTED",
                                    "candidate_action": "cooldown_profile_and_switch",
                                    "confidence": "medium",
                                },
                                "evidence_paths": [str(unknown_state_evidence_path)],
                            }
                        },
                        "no_ai_token_used": True,
                    }
                ),
                encoding="utf-8",
            )
            review_policy_candidate(
                offline_path,
                candidate_state="CAPTCHA_DETECTED",
                candidate_action="cooldown_profile_and_switch",
                decision="approved",
                reviewer="ops",
                note="重复未知状态均指向验证码阻断。",
            )
            repair_dir = base / "reports" / "acceptance_remediation"
            repair_dir.mkdir(parents=True, exist_ok=True)
            account_plan_path = repair_dir / "latest_account_repair_plan.json"
            account_plan_md_path = repair_dir / "latest_account_repair_plan.md"
            account_apply_path = repair_dir / "latest_account_repair_apply.json"
            account_plan_path.write_text(
                json.dumps(
                    {
                        "batch_id": "batch-1",
                        "batch_status": "blocked",
                        "profile_group": "US",
                        "total_unique_profiles_by_error": 1,
                        "total_error_events_by_error": 3,
                        "summary_only_error_count": 2,
                        "operator_steps": ["完成 TikTok 登录后重新预检。"],
                        "groups": [
                            {
                                "error": "LOGIN_REQUIRED",
                                "count": 3,
                                "profile_ids": ["profile-1"],
                                "profile_ids_total": 1,
                                "summary_only_count": 2,
                                "recommended_action": "完成 TikTok 登录或移出执行分组。",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            account_plan_md_path.write_text("# account repair\n", encoding="utf-8")
            account_apply_path.write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "profile_group": "US",
                        "selected_count": 1,
                        "moved_count": 1,
                        "failed_count": 0,
                        "results": [{"profile_id": "profile-1", "attempted": True, "ok": True}],
                        "safety_contract": {
                            "schema_version": "reachops.account_repair_safety_contract.v1",
                            "manual_apply_required": True,
                            "operator_confirmed_apply": True,
                            "hard_blocker_only": True,
                            "moves_only_to_quarantine_group": True,
                            "no_browser_started": True,
                            "no_submit": True,
                            "no_ai_token_used": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            delivery_check_path = repair_dir / "latest_delivery_check.json"
            delivery_check_path.write_text(
                json.dumps(
                    {
                        "status": "blocked_by_accounts",
                        "account_support_handoff": {
                            "schema_version": "reachops.account_support_handoff.v1",
                            "support_required": True,
                            "support_case": "account_pool_blocked",
                            "status": "stale_repair_apply",
                            "profile_group": "US",
                            "batch_id": "batch-1",
                            "priority_action": "manually_repair_or_replace_accounts",
                            "ready_for_retest": False,
                            "requires_latest_repair_apply": False,
                            "requires_manual_account_work": True,
                            "blocker_codes": ["account_repair_plan_has_no_auto_applicable_profiles"],
                            "does_not_claim_real_account_pool_ready": True,
                            "latest_apply": {
                                "account_pool_circuit_breaker": {
                                    "triggered": True,
                                    "threshold": 10,
                                    "hard_failure_count": 26,
                                    "latest_available": 0,
                                    "does_not_claim_real_account_pool_ready": True,
                                },
                            },
                            "repair_plan": {
                                "available": True,
                                "profile_count": 1,
                                "auto_apply_profile_count": 0,
                                "non_auto_error_codes": ["LOGIN_REQUIRED"],
                            },
                            "impacted_accounts": {
                                "error_group_count": 1,
                                "error_groups": [
                                    {
                                        "error": "LOGIN_REQUIRED",
                                        "count": 3,
                                        "profile_ids_sample": ["profile-1"],
                                    }
                                ],
                            },
                            "operator_steps": ["人工修复或替换 US 分组账号。"],
                            "retest_commands": [
                                "python tools/reachops_client_delivery_check.py --json",
                                "python tools/reachops_goal_delivery_runner.py --json",
                            ],
                            "retest_checklist": [
                                {
                                    "id": "manual_repair_or_replace_accounts",
                                    "kind": "manual_account_work",
                                    "title": "人工修复或替换执行分组账号",
                                    "command": "",
                                    "expected": "至少保留 1 个可用账号。",
                                    "required": True,
                                    "no_submit": True,
                                },
                                {
                                    "id": "client_delivery_retest",
                                    "kind": "local_gate",
                                    "title": "复跑客户端账号门禁",
                                    "command": "python tools/reachops_client_delivery_check.py --json",
                                    "expected": "profile_available>=1",
                                    "required": True,
                                    "no_submit": True,
                                },
                            ],
                            "acceptance_required": ["profile_available>=1", "status=passed"],
                            "safety_contract": {
                                "apply_alone_is_not_acceptance": True,
                                "no_browser_started": True,
                                "no_submit": True,
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            bundle = build_evidence_bundle(
                base_dir=base,
                execution_plan_path=str(plan_path),
                run_session_path=str(session_path),
                result_path=str(result_path),
                log_path=str(log_path),
                offline_learning_path=str(offline_path),
            )

            self.assertEqual(bundle["schema_version"], "reachops.evidence_bundle.v1")
            self.assertEqual(bundle["summary"]["status"], "completed")
            self.assertTrue(bundle["summary"]["no_ai_token_during_execution"])
            self.assertGreaterEqual(bundle["audit"]["existing_artifact_count"], 4)
            self.assertTrue(any(row["kind"] == "execution_plan" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["kind"] == "page_state_screenshot" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["kind"] == "page_state_sidecar" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["kind"] == "page_state_evidence" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["kind"] == "offline_learning_evidence" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["kind"] == "account_repair_plan" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["kind"] == "account_repair_apply" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["kind"] == "account_support_handoff" and row["exists"] for row in bundle["artifacts"]))
            self.assertTrue(any(row["stage"] == "PLAN" for row in bundle["timeline"]))
            self.assertTrue(any(row["stage"] == "REPAIR" for row in bundle["timeline"]))
            self.assertTrue(any(row["stage"] == "CHECKPOINT" and row["source"] == "run_session.checkpoint" for row in bundle["timeline"]))
            self.assertTrue(any(row["stage"] == "RISK_GATE" and row["reason_code"] == "LIVE_SUBMIT_NOT_AUTHORIZED" for row in bundle["timeline"]))
            self.assertTrue(any(row["stage"] == "PAGE_STATE" and row["state"] == "CAPTCHA_DETECTED" for row in bundle["timeline"]))
            self.assertTrue(any(row["stage"] == "ACCOUNT_HEALTH" and row["cooldown"] and row["source"] == "account_health" for row in bundle["timeline"]))
            self.assertTrue(all(row.get("no_ai_token_used") is True for row in bundle["timeline"]))
            self.assertEqual(bundle["run_session_health"]["schema_version"], "reachops.run_session_health.v1")
            self.assertEqual(bundle["run_session_health"]["state"], "COMPLETED")
            self.assertTrue(bundle["run_session_health"]["terminal"])
            self.assertEqual(bundle["autonomous_execution_summary"]["schema_version"], "reachops.autonomous_execution_summary.v1")
            self.assertTrue(bundle["autonomous_execution_summary"]["autonomous_core_ready"])
            self.assertEqual(bundle["autonomous_execution_summary"]["missing_core_states"], [])
            self.assertTrue(bundle["autonomous_execution_summary"]["valid_state_transitions"])
            self.assertEqual(bundle["autonomous_execution_summary"]["state_transition_violation_count"], 0)
            self.assertIn("PRECHECK", bundle["autonomous_execution_summary"]["observed_states"])
            self.assertIn("PROFILE_OPENING", bundle["autonomous_execution_summary"]["observed_states"])
            self.assertTrue(any(row["stage"] == "RUN_STATE" for row in bundle["timeline"]))
            self.assertEqual(bundle["repair_summary"]["decision_count"], 1)
            self.assertEqual(bundle["repair_summary"]["audit_event_count"], 1)
            self.assertEqual(bundle["repair_summary"]["retry_count"], 1)
            self.assertEqual(bundle["repair_summary"]["audit_events"][0]["schema_version"], "reachops.repair_audit.v1")
            self.assertEqual(bundle["repair_summary"]["audit_events"][0]["retry_after_seconds"], 5)
            self.assertEqual(bundle["repair_summary"]["audit_events"][0]["executable_steps"][0]["step"], "backoff")
            self.assertEqual(bundle["repair_summary"]["repair_step_result_count"], 2)
            self.assertEqual(bundle["repair_summary"]["repair_step_executed_count"], 1)
            self.assertEqual(bundle["repair_summary"]["repair_step_browser_required_count"], 1)
            self.assertEqual(bundle["repair_summary"]["terminal_outcome_counts"]["retry"], 1)
            self.assertEqual(bundle["repair_summary"]["terminal_retry_count"], 1)
            self.assertEqual(bundle["repair_summary"]["repair_step_results"][0]["status"], "executed")
            self.assertEqual(bundle["risk_summary"]["decision_count"], 3)
            self.assertEqual(bundle["risk_summary"]["blocked_count"], 3)
            self.assertEqual(bundle["risk_summary"]["authorization_block_count"], 1)
            self.assertEqual(bundle["risk_summary"]["quota_block_count"], 1)
            self.assertEqual(bundle["risk_summary"]["human_review_required_count"], 1)
            self.assertEqual(bundle["risk_summary"]["risk_action_count"], 5)
            self.assertEqual(bundle["risk_summary"]["risk_category_counts"]["authorization"], 1)
            self.assertEqual(bundle["risk_summary"]["risk_category_counts"]["quota"], 1)
            self.assertEqual(bundle["risk_summary"]["risk_category_counts"]["duplicate_text"], 1)
            self.assertEqual(bundle["risk_summary"]["terminal_outcome_counts"]["blocked_human_review"], 1)
            self.assertEqual(bundle["risk_summary"]["terminal_outcome_counts"]["blocked_wait_or_switch"], 1)
            self.assertEqual(bundle["risk_summary"]["terminal_outcome_counts"]["blocked_rewrite_required"], 1)
            self.assertEqual(bundle["operator_risk_gate_summary"]["schema_version"], "reachops.operator_risk_gate_summary.v1")
            self.assertEqual(bundle["operator_risk_gate_summary"]["row_count"], 3)
            self.assertEqual(bundle["operator_risk_gate_summary"]["blocked_count"], 3)
            self.assertTrue(
                any("DUPLICATE_ACTION_TEXT" in row["risk_gate_summary"] for row in bundle["operator_risk_gate_summary"]["rows"])
            )
            self.assertEqual(bundle["audit"]["operator_risk_gate_blocked_count"], 3)
            self.assertEqual(bundle["risk_policy_summary"]["schema_version"], "reachops.risk_policy_summary.v1")
            self.assertEqual(bundle["risk_policy_summary"]["policy_block_count"], 3)
            self.assertEqual(bundle["risk_policy_summary"]["quota_block_count"], 1)
            self.assertEqual(bundle["risk_policy_summary"]["duplicate_text_block_count"], 1)
            self.assertTrue(any(row["reason_code"] == "DUPLICATE_ACTION_TEXT" for row in bundle["risk_policy_summary"]["evidence_samples"]))
            self.assertEqual(bundle["page_state_summary"]["snapshot_count"], 1)
            self.assertEqual(bundle["page_state_summary"]["captcha_count"], 1)
            self.assertEqual(bundle["page_state_summary"]["blocking_count"], 1)
            self.assertEqual(
                bundle["page_state_repair_coverage"]["schema_version"],
                "reachops.page_state_repair_coverage.v1",
            )
            self.assertTrue(bundle["page_state_repair_coverage"]["all_page_states_covered"])
            self.assertEqual(bundle["page_state_repair_coverage"]["uncovered_count"], 0)
            self.assertEqual(bundle["control_summary"]["event_count"], 2)
            self.assertEqual(bundle["control_summary"]["pause_count"], 1)
            self.assertEqual(bundle["control_summary"]["resume_count"], 1)
            self.assertFalse(bundle["control_summary"]["current_paused"])
            self.assertEqual(bundle["control_summary"]["current_status"], "running")
            self.assertEqual(bundle["account_health_summary"]["schema_version"], "reachops.account_health_summary.v1")
            self.assertEqual(bundle["account_health_summary"]["event_count"], 2)
            self.assertEqual(bundle["account_health_summary"]["cooldown_event_count"], 2)
            self.assertEqual(bundle["account_health_summary"]["consecutive_failure_cooldown_count"], 2)
            self.assertEqual(bundle["account_repair_summary"]["schema_version"], "reachops.account_repair_summary.v1")
            self.assertEqual(bundle["account_repair_summary"]["error_group_count"], 1)
            self.assertEqual(bundle["account_repair_summary"]["total_profiles_by_error"], 1)
            self.assertEqual(bundle["account_repair_summary"]["total_error_events_by_error"], 3)
            self.assertEqual(bundle["account_repair_summary"]["summary_only_error_count"], 2)
            self.assertEqual(bundle["account_repair_summary"]["error_groups"][0]["profile_ids_total"], 1)
            self.assertEqual(bundle["account_repair_summary"]["error_groups"][0]["summary_only_count"], 2)
            self.assertEqual(bundle["account_repair_summary"]["hard_blocker_profile_count"], 1)
            self.assertTrue(bundle["account_repair_summary"]["pending_recheck"])
            self.assertEqual(
                bundle["account_repair_summary"]["safety_contract"]["schema_version"],
                "reachops.account_repair_safety_contract.v1",
            )
            self.assertTrue(bundle["account_repair_summary"]["manual_apply_required"])
            self.assertTrue(bundle["account_repair_summary"]["hard_blocker_only"])
            self.assertTrue(bundle["account_repair_summary"]["no_browser_started"])
            self.assertTrue(bundle["account_repair_summary"]["no_submit"])
            self.assertEqual(
                bundle["account_support_handoff_summary"]["schema_version"],
                "reachops.account_support_handoff_summary.v1",
            )
            self.assertEqual(
                bundle["account_support_handoff_summary"]["handoff_schema_version"],
                "reachops.account_support_handoff.v1",
            )
            self.assertTrue(bundle["account_support_handoff_summary"]["source_exists"])
            self.assertTrue(bundle["account_support_handoff_summary"]["support_required"])
            self.assertEqual(bundle["account_support_handoff_summary"]["support_case"], "account_pool_blocked")
            self.assertEqual(bundle["account_support_handoff_summary"]["priority_action"], "manually_repair_or_replace_accounts")
            self.assertTrue(bundle["account_support_handoff_summary"]["requires_manual_account_work"])
            self.assertEqual(
                bundle["account_support_handoff_summary"]["blocker_codes"],
                ["account_repair_plan_has_no_auto_applicable_profiles"],
            )
            self.assertTrue(bundle["account_support_handoff_summary"]["account_pool_circuit_breaker_triggered"])
            self.assertEqual(bundle["account_support_handoff_summary"]["account_pool_circuit_breaker_threshold"], 10)
            self.assertEqual(bundle["account_support_handoff_summary"]["account_pool_circuit_breaker_hard_failure_count"], 26)
            self.assertEqual(bundle["account_support_handoff_summary"]["account_pool_circuit_breaker_latest_available"], 0)
            self.assertEqual(
                bundle["account_support_handoff_summary"]["retest_checklist"][0]["id"],
                "manual_repair_or_replace_accounts",
            )
            self.assertEqual(
                bundle["account_support_handoff_summary"]["retest_checklist"][1]["command"],
                "python tools/reachops_client_delivery_check.py --json",
            )
            self.assertTrue(bundle["account_support_handoff_summary"]["does_not_claim_real_account_pool_ready"])
            self.assertEqual(bundle["account_support_handoff_summary"]["repair_plan_non_auto_error_codes"], ["LOGIN_REQUIRED"])
            self.assertEqual(bundle["account_support_handoff_summary"]["error_groups"][0]["profile_ids_sample"], ["profile-1"])
            self.assertEqual(bundle["autonomy_readiness_summary"]["schema_version"], "reachops.autonomy_readiness_summary.v1")
            self.assertTrue(bundle["autonomy_readiness_summary"]["ready"])
            self.assertEqual(bundle["autonomy_readiness_summary"]["failed_count"], 0)
            self.assertTrue(
                any(
                    row["name"] == "run_session_health_current" and row["passed"]
                    for row in bundle["autonomy_readiness_summary"]["checks"]
                )
            )
            self.assertTrue(
                any(
                    row["name"] == "run_session_transitions_valid" and row["passed"]
                    for row in bundle["autonomy_readiness_summary"]["checks"]
                )
            )
            self.assertEqual(bundle["product_capability_summary"]["schema_version"], "reachops.product_capability_summary.v1")
            self.assertTrue(bundle["product_capability_summary"]["ready"])
            self.assertEqual(bundle["product_capability_summary"]["passed_count"], 8)
            self.assertEqual(bundle["product_capability_summary"]["failed_count"], 0)
            self.assertTrue(
                any(
                    row["key"] == "phase_3_autonomous_execution" and row["passed"]
                    for row in bundle["product_capability_summary"]["phases"]
                )
            )
            self.assertEqual(bundle["plan_runtime_contract"]["schema_version"], "reachops.plan_runtime_contract_summary.v1")
            self.assertEqual(bundle["plan_runtime_contract"]["contract_schema_version"], "reachops.execution_plan_runtime_contract.v1")
            self.assertTrue(bundle["plan_runtime_contract"]["plan_id_matches"])
            self.assertTrue(bundle["plan_runtime_contract"]["plan_fingerprint_matches"])
            self.assertTrue(bundle["plan_runtime_contract"]["runtime_after_fingerprint_present"])
            self.assertTrue(bundle["plan_runtime_contract"]["cli_args_ignored_for_plan_fields"])
            self.assertEqual(
                bundle["execution_runtime_contract"]["schema_version"],
                "reachops.execution_runtime_contract_summary.v1",
            )
            self.assertEqual(
                bundle["execution_runtime_contract"]["contract_schema_version"],
                "reachops.execution_runtime_contract.v1",
            )
            self.assertEqual(bundle["execution_runtime_contract"]["executor"], "local_program")
            self.assertTrue(bundle["execution_runtime_contract"]["local_program_executor"])
            self.assertTrue(bundle["execution_runtime_contract"]["ai_console_control_surface_only"])
            self.assertTrue(bundle["execution_runtime_contract"]["execution_phase_ai_calls_disallowed"])
            self.assertTrue(bundle["execution_runtime_contract"]["ai_usage_policy_matches_contract"])
            self.assertTrue(bundle["execution_runtime_contract"]["page_state_evidence_required"])
            self.assertTrue(bundle["execution_runtime_contract"]["evidence_bundle_required"])
            self.assertEqual(bundle["ai_usage_summary"]["schema_version"], "reachops.ai_usage_summary.v1")
            self.assertEqual(bundle["ai_usage_summary"]["audit_status"], "pass")
            self.assertEqual(bundle["ai_usage_summary"]["execution_phase_ai_call_count"], 0)
            self.assertEqual(bundle["ai_usage_summary"]["execution_phase_token_estimate"], 0)
            self.assertTrue(bundle["ai_usage_summary"]["no_ai_token_used"])
            self.assertEqual(bundle["offline_learning"]["policy_candidates"]["candidate_count"], 1)
            self.assertEqual(bundle["offline_learning"]["policy_review_summary"]["approved_count"], 1)
            self.assertEqual(
                bundle["offline_learning"]["policy_release_proposal"]["schema_version"],
                "reachops.offline_policy_release_proposal.v1",
            )
            self.assertEqual(bundle["offline_learning"]["policy_release_proposal"]["ready_for_release_count"], 1)
            self.assertEqual(bundle["offline_learning"]["policy_release_proposal"]["runtime_auto_apply_count"], 0)
            self.assertFalse(bundle["offline_learning"]["policy_release_proposal"]["runtime_auto_apply"])
            self.assertEqual(bundle["operator_summary"]["schema_version"], "reachops.operator_summary.v1")
            self.assertTrue(bundle["operator_summary"]["no_ai_token_used"])
            self.assertEqual(bundle["operator_summary"]["proof"]["ai_usage_audit_status"], "pass")
            self.assertEqual(bundle["operator_summary"]["proof"]["execution_phase_ai_call_count"], 0)
            self.assertTrue(bundle["operator_summary"]["proof"]["autonomy_ready"])
            self.assertTrue(bundle["operator_summary"]["proof"]["product_capability_ready"])
            self.assertTrue(bundle["operator_summary"]["proof"]["page_state_repair_all_covered"])
            self.assertEqual(bundle["operator_summary"]["proof"]["page_state_repair_uncovered_count"], 0)
            self.assertEqual(bundle["operator_summary"]["proof"]["offline_policy_runtime_auto_apply_count"], 0)
            self.assertEqual(bundle["operator_summary"]["proof"]["offline_policy_release_ready_count"], 1)
            self.assertEqual(bundle["operator_summary"]["proof"]["offline_policy_release_runtime_auto_apply_count"], 0)
            self.assertTrue(bundle["operator_summary"]["proof"]["account_repair_manual_apply_required"])
            self.assertTrue(bundle["operator_summary"]["proof"]["account_repair_hard_blocker_only"])
            self.assertTrue(bundle["operator_summary"]["proof"]["account_repair_no_submit"])
            self.assertIn("复核离线学习候选规则", " ".join(bundle["operator_summary"]["next_actions"]))
            self.assertTrue(any(row["stage"] == "CONTROL" for row in bundle["timeline"]))
            self.assertEqual(bundle["audit"]["repair_decision_count"], 1)
            self.assertEqual(bundle["audit"]["risk_gate_decision_count"], 3)
            self.assertEqual(bundle["audit"]["risk_policy_block_count"], 3)
            self.assertEqual(bundle["audit"]["risk_policy_duplicate_text_block_count"], 1)
            self.assertEqual(bundle["audit"]["page_state_snapshot_count"], 1)
            self.assertEqual(bundle["audit"]["control_event_count"], 2)
            self.assertTrue(bundle["audit"]["page_state_repair_all_covered"])
            self.assertEqual(bundle["audit"]["page_state_repair_coverage_uncovered_count"], 0)
            self.assertEqual(bundle["audit"]["account_health_event_count"], 2)
            self.assertEqual(bundle["audit"]["account_health_cooldown_event_count"], 2)
            self.assertEqual(bundle["audit"]["page_state_artifact_count"], 3)
            self.assertEqual(bundle["audit"]["page_state_screenshot_artifact_count"], 1)
            self.assertEqual(bundle["audit"]["page_state_sidecar_artifact_count"], 1)
            self.assertEqual(bundle["audit"]["offline_learning_artifact_count"], 1)
            self.assertEqual(bundle["audit"]["account_repair_artifact_count"], 3)
            self.assertEqual(bundle["audit"]["account_support_handoff_artifact_count"], 1)
            self.assertTrue(bundle["audit"]["account_support_handoff_source_exists"])
            self.assertTrue(bundle["audit"]["account_support_handoff_support_required"])
            self.assertFalse(bundle["audit"]["account_support_handoff_ready_for_retest"])
            self.assertTrue(bundle["audit"]["account_support_handoff_does_not_claim_ready"])
            self.assertTrue(bundle["audit"]["account_support_handoff_circuit_breaker_triggered"])
            self.assertEqual(bundle["audit"]["account_support_handoff_circuit_breaker_hard_failure_count"], 26)
            self.assertEqual(bundle["audit"]["account_repair_error_group_count"], 1)
            self.assertTrue(bundle["audit"]["account_repair_pending_recheck"])
            self.assertTrue(bundle["audit"]["account_repair_manual_apply_required"])
            self.assertTrue(bundle["audit"]["account_repair_hard_blocker_only"])
            self.assertTrue(bundle["audit"]["account_repair_no_browser_started"])
            self.assertTrue(bundle["audit"]["account_repair_no_submit"])
            self.assertTrue(bundle["audit"]["autonomy_ready"])
            self.assertEqual(bundle["audit"]["autonomy_failed_count"], 0)
            self.assertTrue(bundle["audit"]["autonomous_core_ready"])
            self.assertEqual(bundle["audit"]["autonomous_missing_core_states"], [])
            self.assertTrue(bundle["audit"]["product_capability_ready"])
            self.assertEqual(bundle["audit"]["product_capability_failed_count"], 0)
            self.assertTrue(bundle["audit"]["execution_plan_contract_present"])
            self.assertTrue(bundle["audit"]["execution_plan_contract_plan_id_matches"])
            self.assertTrue(bundle["audit"]["execution_plan_contract_fingerprint_matches"])
            self.assertTrue(bundle["audit"]["execution_plan_runtime_after_fingerprint_present"])
            self.assertTrue(bundle["audit"]["execution_plan_contract_ignored_cli_args"])
            self.assertTrue(bundle["audit"]["execution_runtime_contract_present"])
            self.assertTrue(bundle["audit"]["execution_runtime_contract_local_program"])
            self.assertTrue(bundle["audit"]["execution_runtime_contract_ai_control_surface_only"])
            self.assertTrue(bundle["audit"]["execution_runtime_contract_ai_calls_disallowed"])
            self.assertTrue(bundle["audit"]["execution_runtime_contract_ai_usage_policy_matches"])
            self.assertTrue(bundle["audit"]["execution_runtime_contract_evidence_required"])
            self.assertTrue(bundle["audit"]["autonomous_preflight_forecast_exists"])
            self.assertTrue(bundle["audit"]["autonomous_preflight_forecast_ready"])
            self.assertGreaterEqual(bundle["audit"]["autonomous_preflight_repair_route_count"], 5)
            self.assertGreaterEqual(bundle["audit"]["autonomous_preflight_evidence_requirement_count"], 4)
            self.assertEqual(bundle["autonomous_preflight_forecast"]["forecast_schema_version"], "reachops.autonomous_preflight_forecast.v1")
            self.assertEqual(bundle["autonomous_preflight_forecast"]["source"], "persisted_in_execution_plan")
            self.assertTrue(bundle["autonomous_preflight_forecast"]["persisted"])
            self.assertIn("REPAIRING", bundle["autonomous_preflight_forecast"]["predicted_state_sequence"])
            self.assertEqual(
                bundle["autonomous_preflight_reconciliation"]["schema_version"],
                "reachops.autonomous_preflight_reconciliation.v1",
            )
            self.assertIn(bundle["autonomous_preflight_reconciliation"]["status"], {"matched", "partially_matched"})
            self.assertGreaterEqual(bundle["autonomous_preflight_reconciliation"]["matched_route_count"], 1)
            self.assertIn("CAPTCHA_DETECTED", bundle["autonomous_preflight_reconciliation"]["actual_page_states"])
            self.assertTrue(
                any(
                    row["state"] == "CAPTCHA_DETECTED"
                    for row in bundle["autonomous_preflight_reconciliation"]["matched_routes"]
                )
            )
            self.assertEqual(
                bundle["audit"]["autonomous_preflight_reconciliation_status"],
                bundle["autonomous_preflight_reconciliation"]["status"],
            )
            self.assertGreaterEqual(bundle["audit"]["autonomous_preflight_matched_route_count"], 1)
            self.assertTrue(bundle["audit"]["autonomous_valid_state_transitions"])
            self.assertEqual(bundle["audit"]["autonomous_state_transition_violation_count"], 0)
            self.assertEqual(bundle["audit"]["offline_policy_candidate_count"], 1)
            self.assertEqual(bundle["audit"]["offline_policy_review_count"], 1)
            self.assertEqual(bundle["audit"]["offline_policy_approved_count"], 1)
            self.assertEqual(bundle["audit"]["offline_policy_runtime_auto_apply_count"], 0)
            self.assertEqual(bundle["audit"]["offline_policy_release_ready_count"], 1)
            self.assertEqual(bundle["audit"]["offline_policy_release_runtime_auto_apply_count"], 0)
            self.assertIn("No AI token during execution: True", render_evidence_markdown(bundle))
            self.assertIn("ExecutionPlan Runtime Contract", render_evidence_markdown(bundle))
            self.assertIn("Page State Repair Coverage", render_evidence_markdown(bundle))
            self.assertIn("All covered: true", render_evidence_markdown(bundle))
            self.assertIn("Autonomous Preflight Forecast", render_evidence_markdown(bundle))
            self.assertIn("Autonomous Preflight Reconciliation", render_evidence_markdown(bundle))
            self.assertIn("Matched route: CAPTCHA_DETECTED", render_evidence_markdown(bundle))
            self.assertIn("Source: persisted_in_execution_plan", render_evidence_markdown(bundle))
            self.assertIn("Persisted in plan: true", render_evidence_markdown(bundle))
            self.assertIn("Repair route: UNKNOWN_PAGE_STATE", render_evidence_markdown(bundle))
            self.assertIn("Evidence: run_session_state_history", render_evidence_markdown(bundle))
            self.assertIn("Plan fingerprint matches: true", render_evidence_markdown(bundle))
            self.assertIn("Runtime after fingerprint present: true", render_evidence_markdown(bundle))
            self.assertIn("CLI args ignored for plan fields: true", render_evidence_markdown(bundle))
            self.assertIn("Operator Summary", render_evidence_markdown(bundle))
            self.assertIn("Autonomy Readiness Summary", render_evidence_markdown(bundle))
            self.assertIn("execution_plan_replayable: pass", render_evidence_markdown(bundle))
            self.assertIn("run_session_health_current: pass", render_evidence_markdown(bundle))
            self.assertIn("Product Capability Summary", render_evidence_markdown(bundle))
            self.assertIn("phase_3_autonomous_execution: pass", render_evidence_markdown(bundle))
            self.assertIn("Repair Summary", render_evidence_markdown(bundle))
            self.assertIn("Audit events: 1", render_evidence_markdown(bundle))
            self.assertIn("Repair Machine Actions", render_evidence_markdown(bundle))
            self.assertIn("backoff(seconds=5)", render_evidence_markdown(bundle))
            self.assertIn("Repair step results: 2", render_evidence_markdown(bundle))
            self.assertIn("Repair steps needing browser executor: 1", render_evidence_markdown(bundle))
            self.assertIn("Risk Summary", render_evidence_markdown(bundle))
            self.assertIn("Risk Policy Summary", render_evidence_markdown(bundle))
            self.assertIn("Duplicate text blocks: 1", render_evidence_markdown(bundle))
            self.assertIn("Account Health Summary", render_evidence_markdown(bundle))
            self.assertIn("Consecutive failure cooldown: 2", render_evidence_markdown(bundle))
            self.assertIn("Account Repair Summary", render_evidence_markdown(bundle))
            self.assertIn("Pending recheck: true", render_evidence_markdown(bundle))
            self.assertIn("Account Support Handoff", render_evidence_markdown(bundle))
            self.assertIn("Support case: account_pool_blocked", render_evidence_markdown(bundle))
            self.assertIn("Priority action: manually_repair_or_replace_accounts", render_evidence_markdown(bundle))
            self.assertIn("Does not claim real account pool ready: true", render_evidence_markdown(bundle))
            self.assertIn(
                "Account pool circuit breaker: triggered hard_failures=26 threshold=10 latest_available=0",
                render_evidence_markdown(bundle),
            )
            self.assertIn("Non-auto errors: LOGIN_REQUIRED", render_evidence_markdown(bundle))
            self.assertIn("Retest command: python tools/reachops_client_delivery_check.py --json", render_evidence_markdown(bundle))
            self.assertIn("Retest checklist: manual_repair_or_replace_accounts", render_evidence_markdown(bundle))
            self.assertIn("Human review required: 1", render_evidence_markdown(bundle))
            self.assertIn("Risk Gate Machine Actions", render_evidence_markdown(bundle))
            self.assertIn("request_operator_authorization(required=true)", render_evidence_markdown(bundle))
            self.assertIn("Operator Risk Gate Summary", render_evidence_markdown(bundle))
            self.assertIn("Primary reason: 风险门禁阻断 / LIVE_SUBMIT_NOT_AUTHORIZED", render_evidence_markdown(bundle))
            self.assertIn("改写或轮换话术后重试", render_evidence_markdown(bundle))
            self.assertIn("Page State Summary", render_evidence_markdown(bundle))
            self.assertIn("Page state screenshot: exists", render_evidence_markdown(bundle))
            self.assertIn("Page state sidecar: exists", render_evidence_markdown(bundle))
            self.assertIn("Offline learning evidence: exists", render_evidence_markdown(bundle))
            self.assertIn("Page State Counts", render_evidence_markdown(bundle))
            self.assertIn("CAPTCHA_DETECTED: 1", render_evidence_markdown(bundle))
            self.assertIn("Control Summary", render_evidence_markdown(bundle))
            self.assertIn("Current paused: false", render_evidence_markdown(bundle))
            self.assertIn("Run Session Health", render_evidence_markdown(bundle))
            self.assertIn("Terminal: true", render_evidence_markdown(bundle))
            self.assertIn("Autonomous Execution Summary", render_evidence_markdown(bundle))
            self.assertIn("Core ready: true", render_evidence_markdown(bundle))
            self.assertIn("AI Usage Summary", render_evidence_markdown(bundle))
            self.assertIn("Offline Policy Candidates", render_evidence_markdown(bundle))

    def test_bundle_derives_autonomous_preflight_forecast_for_legacy_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = build_execution_plan(target="anti aging serum", mode="collect", base_dir=str(base))
            plan_path = write_execution_plan(plan, base / "plans" / "legacy_plan.json")
            session = create_run_session(
                plan,
                execution_plan_path=str(plan_path),
                result_path=str(base / "result.json"),
                log_path=str(base / "runtime.log"),
            )
            session = transition_run_session(session, "BLOCKED", result={"status": "blocked", "error": "LOGIN_REQUIRED"})
            session_path = write_run_session(session, base / "runs" / "run.json")
            result_path = base / "result.json"
            result_path.write_text(json.dumps({"status": "blocked", "error": "LOGIN_REQUIRED"}), encoding="utf-8")
            log_path = base / "runtime.log"
            log_path.write_text("ERROR LOGIN_REQUIRED\n", encoding="utf-8")

            bundle = build_evidence_bundle(
                base_dir=base,
                execution_plan_path=str(plan_path),
                run_session_path=str(session_path),
                result_path=str(result_path),
                log_path=str(log_path),
            )

            forecast = bundle["autonomous_preflight_forecast"]
            self.assertTrue(forecast["exists"])
            self.assertFalse(forecast["persisted"])
            self.assertEqual(forecast["source"], "derived_from_execution_plan")
            self.assertEqual(forecast["forecast_schema_version"], "reachops.autonomous_preflight_forecast.v1")
            self.assertTrue(any(row["state"] == "LOGIN_REQUIRED" for row in forecast["repair_routes"]))
            markdown = render_evidence_markdown(bundle)
            self.assertIn("Source: derived_from_execution_plan", markdown)
            self.assertIn("Persisted in plan: false", markdown)

    def test_autonomy_readiness_fails_for_stale_run_session_health(self) -> None:
        summary = build_autonomy_readiness_summary(
            plan_runtime_contract={
                "plan_id_matches": True,
                "plan_fingerprint_matches": True,
                "runtime_after_fingerprint_present": True,
            },
            ai_usage_summary={
                "audit_status": "pass",
                "execution_phase_ai_call_count": 0,
                "execution_phase_token_estimate": 0,
            },
            repair_summary={"decision_count": 1},
            risk_summary={"decision_count": 1},
            page_state_summary={"snapshot_count": 1},
            control_summary={"event_count": 1},
            autonomous_execution_summary={
                "checkpoint_present": True,
                "state_history_count": 2,
                "autonomous_core_ready": False,
                "observed_states": ["CREATED", "COLLECTING"],
                "missing_core_states": ["PRECHECK", "PROFILE_OPENING"],
                "terminal_state_observed": False,
            },
            run_session_health={
                "schema_version": "reachops.run_session_health.v1",
                "status": "stale",
                "stale": True,
                "age_seconds": 181,
                "last_stage": "COLLECTING profile=profile-1",
            },
            account_health_summary={"event_count": 1},
            account_repair_summary={"plan_exists": False},
            offline_learning={"record_count": 0, "policy_candidates": {}},
            audit={"timeline_count": 1, "control_event_count": 1, "existing_artifact_count": 1},
        )
        health_check = next(row for row in summary["checks"] if row["name"] == "run_session_health_current")
        self.assertFalse(summary["ready"])
        self.assertFalse(health_check["passed"])
        self.assertIn("run_session_health_current", summary["failed_checks"])

    def test_ai_usage_summary_ignores_no_token_audit_marker(self) -> None:
        plan = build_execution_plan(target="anti aging serum")
        session = create_run_session(plan)
        summary = build_ai_usage_summary(
            session,
            plan,
            [
                "CHECK local_ai_console intent=product_capability_status no_ai_token_used=true",
                "DONE run completed no_ai_token_used=true",
            ],
        )
        self.assertEqual(summary["audit_status"], "pass")
        self.assertEqual(summary["suspicious_log_event_count"], 0)
        self.assertTrue(summary["no_ai_token_used"])

    def test_ai_usage_summary_flags_real_ai_token_marker(self) -> None:
        plan = build_execution_plan(target="anti aging serum")
        session = create_run_session(plan)
        summary = build_ai_usage_summary(
            session,
            plan,
            ["WARN external_ai provider=openai ai_token_used=true"],
        )
        self.assertEqual(summary["audit_status"], "fail")
        self.assertEqual(summary["suspicious_log_event_count"], 1)
        self.assertIn("execution_log_contains_ai_call_marker", summary["violations"])

    def test_product_capability_phase_3_gap_names_missing_core_states(self) -> None:
        summary = build_product_capability_summary(
            plan_runtime_contract={
                "plan_id_matches": True,
                "plan_fingerprint_matches": True,
                "runtime_after_fingerprint_present": True,
            },
            run_session_health={
                "schema_version": "reachops.run_session_health.v1",
                "status": "terminal",
                "stale": False,
            },
            ai_usage_summary={
                "audit_status": "pass",
                "execution_phase_ai_call_count": 0,
                "execution_phase_token_estimate": 0,
            },
            autonomy_readiness_summary={
                "checks": [
                    {"name": "run_session_checkpointed", "passed": True},
                    {"name": "autonomous_state_machine_core_covered", "passed": False},
                    {"name": "run_session_health_current", "passed": True},
                ]
            },
            repair_summary={"decision_count": 0},
            risk_summary={"decision_count": 0},
            page_state_summary={"snapshot_count": 0},
            control_summary={"event_count": 0},
            autonomous_execution_summary={
                "missing_core_states": ["PRECHECK", "PROFILE_OPENING"],
                "terminal_state_observed": True,
            },
            account_health_summary={"event_count": 0},
            account_repair_summary={"plan_exists": False},
            offline_learning={"record_count": 0, "policy_candidates": {}},
            audit={"existing_artifact_count": 1},
        )
        phase_3 = next(row for row in summary["phases"] if row["key"] == "phase_3_autonomous_execution")
        self.assertFalse(phase_3["passed"])
        self.assertIn("PRECHECK", phase_3["next_action"])
        self.assertIn("PROFILE_OPENING", phase_3["next_action"])

    def test_risk_policy_summary_explains_profile_group_blocks(self) -> None:
        summary = build_risk_policy_summary(
            {
                "decisions": [
                    {
                        "allowed": False,
                        "reason_code": "profile_group_not_found",
                        "risk_actions": [
                            {"step": "block_execution", "required": True},
                            {"step": "refresh_profile_groups", "required": True},
                            {"step": "reselect_profile_group", "required": True},
                        ],
                    }
                ],
                "authorization_block_count": 0,
                "quota_block_count": 0,
                "rate_limit_block_count": 0,
                "cooldown_block_count": 0,
                "human_review_required_count": 0,
            }
        )
        self.assertEqual(summary["profile_group_block_count"], 1)
        self.assertIn("刷新 ixBrowser 配置分组", " ".join(summary["next_actions"]))

    def test_autonomous_summary_compacts_duplicate_state_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = build_execution_plan(target="anti aging serum", mode="collect", base_dir=str(base))
            plan_path = write_execution_plan(plan, base / "plans" / "plan.json")
            session = create_run_session(plan, execution_plan_path=str(plan_path))
            duplicate = {
                "at": "2026-07-05T00:00:00Z",
                "state": "COMPLETED",
                "status": "completed",
                "last_stage": "DONE local no_ai_token_used=true",
                "runtime_state_inferred": "",
                "log_line_count": 0,
                "source": "legacy_poll",
                "no_ai_token_used": True,
            }
            session["state"] = "COMPLETED"
            session["status"] = "completed"
            session["checkpoint"] = {"state": "COMPLETED", "last_stage": "DONE local no_ai_token_used=true"}
            session["state_history"] = [duplicate, dict(duplicate), dict(duplicate)]
            session_path = write_run_session(session, base / "runs" / "run.json")
            log_path = base / "runtime.log"
            log_path.write_text("DONE local no_ai_token_used=true\n", encoding="utf-8")
            bundle = build_evidence_bundle(
                base_dir=base,
                execution_plan_path=str(plan_path),
                run_session_path=str(session_path),
                log_path=str(log_path),
            )
            auto = bundle["autonomous_execution_summary"]
            self.assertEqual(auto["raw_state_history_count"], 3)
            self.assertEqual(auto["state_history_count"], 1)
            self.assertTrue(auto["state_history_compacted"])

    def test_precheck_blocked_run_can_satisfy_autonomous_core(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = build_execution_plan(target="anti aging serum", mode="collect", base_dir=str(base))
            plan_path = write_execution_plan(plan, base / "plans" / "plan.json")
            session = create_run_session(plan, execution_plan_path=str(plan_path))
            session = transition_run_session(session, "PRECHECK", last_stage="PRECHECK start blocked")
            session = transition_run_session(
                session,
                "BLOCKED",
                last_stage="PRECHECK_BLOCKED reason=profile_group_not_found",
                result={
                    "status": "blocked",
                    "error": "profile_group_not_found",
                    "reason": "profile_group_not_found",
                    "no_ai_token_during_execution": True,
                },
            )
            session_path = write_run_session(session, base / "runs" / "run.json")
            bundle = build_evidence_bundle(
                base_dir=base,
                execution_plan_path=str(plan_path),
                run_session_path=str(session_path),
            )
            auto = bundle["autonomous_execution_summary"]
            self.assertTrue(auto["precheck_blocked"])
            self.assertEqual(auto["required_core_states"], ["CREATED", "PRECHECK", "BLOCKED"])
            self.assertEqual(auto["missing_core_states"], [])
            self.assertTrue(auto["autonomous_core_ready"])
            self.assertTrue(auto["valid_state_transitions"])
            self.assertEqual(auto["state_transition_violation_count"], 0)

    def test_invalid_state_transition_blocks_autonomous_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = build_execution_plan(target="anti aging serum", mode="collect", base_dir=str(base))
            plan_path = write_execution_plan(plan, base / "plans" / "plan.json")
            session = create_run_session(plan, execution_plan_path=str(plan_path))
            session = transition_run_session(session, "EXECUTING", last_stage="invalid direct execution")
            session = transition_run_session(session, "BLOCKED", result={"status": "blocked", "error": "invalid_transition"})
            session_path = write_run_session(session, base / "runs" / "run.json")
            bundle = build_evidence_bundle(
                base_dir=base,
                execution_plan_path=str(plan_path),
                run_session_path=str(session_path),
            )
            auto = bundle["autonomous_execution_summary"]
            self.assertFalse(auto["valid_state_transitions"])
            self.assertGreaterEqual(auto["state_transition_violation_count"], 1)
            self.assertFalse(auto["autonomous_core_ready"])
            self.assertFalse(bundle["audit"]["autonomous_valid_state_transitions"])
            self.assertGreaterEqual(bundle["audit"]["autonomous_state_transition_violation_count"], 1)
            transition_check = next(
                row for row in bundle["autonomy_readiness_summary"]["checks"] if row["name"] == "run_session_transitions_valid"
            )
            self.assertFalse(transition_check["passed"])
            self.assertIn("Valid state transitions: false", render_evidence_markdown(bundle))

    def test_write_bundle_and_markdown_latest_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            bundle = {
                "schema_version": "reachops.evidence_bundle.v1",
                "bundle_id": "bundle_test",
                "plan_id": "plan_test",
                "session_id": "run_test",
                "summary": {"status": "completed", "no_ai_token_during_execution": True},
                "artifacts": [],
                "timeline": [],
            }
            write_evidence_bundle(bundle, base / "bundle.json", base / "latest.json")
            write_evidence_markdown(bundle, base / "bundle.md", base / "latest.md")
            self.assertTrue((base / "bundle.json").is_file())
            self.assertTrue((base / "latest.json").is_file())
            self.assertTrue((base / "bundle.md").is_file())
            self.assertTrue((base / "latest.md").is_file())


if __name__ == "__main__":
    unittest.main()

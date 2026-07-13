# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from ReachOps.ai_console import LocalAIConsole


class LocalAIConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.console = LocalAIConsole(base_dir="/tmp/reachops-test", max_profile_limit=20)
        self.form = {
            "target": "anti aging serum",
            "sourceType": "keyword",
            "group": "United States",
            "mode": "preflight",
            "volume": "quick",
            "profiles": "3",
            "commentText": "",
            "liveConfirm": False,
            "groupListReady": True,
        }

    def test_collect_only_message_builds_collect_execution_plan(self) -> None:
        result = self.console.handle("只采集不评论", form=self.form)
        self.assertEqual(result["intent"], "plan_update")
        self.assertTrue(result["no_ai_token_used"])
        self.assertEqual(result["ai_usage_ledger"]["operator_console"]["local_rule_call_count"], 1)
        self.assertEqual(result["ai_usage_ledger"]["execution_phase"]["ai_call_count"], 0)
        self.assertEqual(result["ai_usage_ledger"]["execution_phase"]["token_estimate"], 0)
        self.assertEqual(result["plan_patch"]["mode"], "collect")
        self.assertFalse(result["plan_patch"]["liveConfirm"])
        self.assertEqual(result["execution_plan"]["mode"], "collect")
        self.assertFalse(result["execution_plan"]["authorization"]["live_confirmed"])
        self.assertEqual(result["preflight_decision"]["schema_version"], "reachops.start_preflight_decision.v1")
        self.assertEqual(result["autonomous_preflight_forecast"]["schema_version"], "reachops.autonomous_preflight_forecast.v1")
        self.assertIn("REPAIRING", result["autonomous_preflight_forecast"]["predicted_state_sequence"])
        self.assertTrue(
            any(row["state"] == "UNKNOWN_PAGE_STATE" for row in result["autonomous_preflight_forecast"]["repair_routes"])
        )
        self.assertTrue(result["autonomous_preflight_forecast"]["runtime_invariants"]["no_ai_token_during_execution"])

    def test_operator_sentence_extracts_target_into_execution_plan(self) -> None:
        empty_form = {
            "target": "",
            "sourceType": "keyword",
            "group": "Canada",
            "mode": "preflight",
            "volume": "quick",
            "profiles": "5",
            "liveConfirm": False,
        }
        result = self.console.handle("帮我采集抗衰精华，只采集不评论", form=empty_form)
        self.assertEqual(result["intent"], "plan_update")
        self.assertEqual(result["plan_patch"]["target"], "抗衰精华")
        self.assertEqual(result["plan_patch"]["mode"], "collect")
        self.assertEqual(result["execution_plan"]["target"], "抗衰精华")
        self.assertEqual(result["execution_plan"]["source_type"], "keyword")
        self.assertEqual(result["execution_plan"]["profile_group"], "Canada")
        self.assertEqual(result["execution_plan"]["limits"]["profile_limit"], 5)
        self.assertTrue(result["execution_plan_id"].startswith("plan_"))
        self.assertTrue(result["no_ai_token_used"])
        self.assertEqual(result["ai_usage_ledger"]["audit_status"], "pass")
        self.assertEqual(result["autonomous_preflight_forecast"]["plan_id"], result["execution_plan_id"])

    def test_live_comment_requires_explicit_confirmation(self) -> None:
        result = self.console.handle("切到真实评论", form=self.form)
        self.assertEqual(result["execution_plan"]["mode"], "live_comment")
        self.assertFalse(result["execution_plan"]["authorization"]["live_confirmed"])
        self.assertIn("真实评论仍需要明确授权", result["reply"])

    def test_live_comment_confirmation_sets_authorization(self) -> None:
        result = self.console.handle("已授权，我确认真实评论", form=self.form)
        self.assertEqual(result["execution_plan"]["mode"], "live_comment")
        self.assertTrue(result["execution_plan"]["authorization"]["live_confirmed"])
        self.assertTrue(result["execution_plan"]["authorization"]["live_submit_allowed"])

    def test_product_capability_question_explains_phase_matrix_without_tokens(self) -> None:
        runtime = {
            "evidence_bundle": {
                "schema_version": "reachops.evidence_bundle.v1",
                "bundle_id": "bundle_capability",
                "product_capability_summary": {
                    "schema_version": "reachops.product_capability_summary.v1",
                    "ready": False,
                    "passed_count": 6,
                    "failed_count": 2,
                    "failed_phases": ["phase_4_page_state_sensing", "phase_8_evidence_delivery_loop"],
                    "next_actions": ["补齐页面快照、DOM 摘要、截图或未知状态包。"],
                    "phases": [
                        {"phase": 1, "key": "phase_1_unified_client_runtime", "title": "统一产品骨架", "passed": True},
                        {"phase": 3, "key": "phase_3_autonomous_execution", "title": "本地自治执行引擎", "passed": True},
                        {"phase": 4, "key": "phase_4_page_state_sensing", "title": "页面状态感知", "passed": False, "next_action": "补齐页面快照、DOM 摘要、截图或未知状态包。"},
                        {"phase": 8, "key": "phase_8_evidence_delivery_loop", "title": "证据与交付闭环", "passed": False, "next_action": "补齐证据产物、时间线、离线学习或报告首页。"},
                    ],
                },
                "autonomy_readiness_summary": {
                    "schema_version": "reachops.autonomy_readiness_summary.v1",
                    "ready": False,
                    "failed_count": 1,
                },
                "operator_summary": {
                    "schema_version": "reachops.operator_summary.v1",
                    "next_actions": ["查看证据包。"],
                },
            },
            "delivery_boundary": {
                "schema_version": "reachops.delivery_boundary.v1",
                "local_product_capability_ready": True,
                "final_delivery_ready": False,
                "external_validation_pending": True,
                "windows_final_artifacts_pending": True,
                "final_delivery_evidence_plan": {
                    "schema_version": "reachops.final_delivery_evidence_plan.v1",
                    "ready": False,
                    "pending_scopes": ["external_authorized_execution", "windows_final_artifacts"],
                    "items": [
                        {
                            "scope": "external_authorized_execution",
                            "next_action": "完成授权真实触达验收。",
                            "commands": ["python tools\\reachops_goal_status_report.py --strict-external --json"],
                        },
                        {
                            "scope": "windows_final_artifacts",
                            "next_action": "生成 Windows 最终包。",
                            "commands": ["python tools\\reachops_delivery_package_check.py --json"],
                        },
                    ],
                },
            },
        }
        result = self.console.handle("产品能力矩阵现在做到哪了", form=self.form, runtime=runtime)
        self.assertEqual(result["intent"], "product_capability_status")
        self.assertTrue(result["no_ai_token_used"])
        self.assertIn("产品能力矩阵 ready=false", result["reply"])
        self.assertIn("未闭环阶段：4. 页面状态感知", result["reply"])
        self.assertIn("待补证据：external_authorized_execution、windows_final_artifacts", result["reply"])
        self.assertEqual(result["product_capability_summary"]["failed_count"], 2)
        self.assertEqual(result["evidence_bundle"]["product_capability_summary"]["schema_version"], "reachops.product_capability_summary.v1")
        self.assertEqual(result["final_delivery_evidence_plan"]["schema_version"], "reachops.final_delivery_evidence_plan.v1")
        self.assertEqual(
            result["evidence_bundle"]["final_delivery_evidence_plan"]["pending_scopes"],
            ["external_authorized_execution", "windows_final_artifacts"],
        )
        self.assertTrue(any("八阶段" in row for row in result["machine_actions"]))
        self.assertTrue(any("final_delivery_evidence_plan" in row for row in result["machine_actions"]))
        self.assertTrue(any("phase_4_page_state_sensing" in row for row in result["timeline_summary"]))
        self.assertIn("补齐页面快照", result["next_actions"][0])
        self.assertEqual(result["ai_usage_ledger"]["execution_phase"]["ai_call_count"], 0)
        self.assertEqual(result["ai_usage_ledger"]["operator_console"]["ai_call_count"], 0)

    def test_status_question_explains_current_blocker(self) -> None:
        runtime = {
            "run_session": {"state": "BLOCKED", "result": {"reason": "LOGIN_REQUIRED"}},
            "run_result": {},
            "acceptance": {
                "client_delivery": {
                    "blockers": ["账号预检没有可用账号"],
                    "failed_checks": [],
                    "next_actions": [
                        "批量筛出 IXBROWSER_KERNEL_MISMATCH 账号，修改内核版本或移出执行分组。 本批次账号: 24919,24922,24923",
                        "先在 ixBrowser 手动打开 United States 中至少 1 个账号。",
                    ],
                },
                "acceptance": {"blockers": []},
            },
            "final_delivery_evidence_plan": {
                "schema_version": "reachops.final_delivery_evidence_plan.v1",
                "ready": False,
                "pending_scopes": ["external_authorized_execution"],
                "items": [
                    {
                        "scope": "external_authorized_execution",
                        "next_action": "完成授权真实触达验收。",
                        "commands": ["python tools\\reachops_goal_status_report.py --strict-external --json"],
                    }
                ],
            },
        }
        result = self.console.handle("最终交付还差什么证据", form=self.form, runtime=runtime)
        self.assertEqual(result["intent"], "product_capability_status")
        self.assertIn("external_authorized_execution", result["reply"])
        self.assertEqual(result["final_delivery_evidence_plan"]["schema_version"], "reachops.final_delivery_evidence_plan.v1")
        result = self.console.handle("为什么停了", form=self.form, runtime=runtime)
        self.assertEqual(result["intent"], "explain_status")
        self.assertEqual(result["run_session_state"], "BLOCKED")
        self.assertIn("账号预检没有可用账号", result["reply"])
        self.assertIn("主要原因：账号预检没有可用账号。", result["reply"])
        self.assertIn("。客户端门禁下一步：批量筛出 IXBROWSER_KERNEL_MISMATCH 账号", result["reply"])
        self.assertIn("客户端门禁下一步：批量筛出 IXBROWSER_KERNEL_MISMATCH 账号", result["reply"])
        self.assertNotIn("no_browser_started=false", result["reply"])
        self.assertEqual(result["client_delivery"]["blockers"], ["账号预检没有可用账号"])
        self.assertEqual(result["client_delivery_summary"]["blocker_count"], 1)
        self.assertEqual(result["client_delivery_summary"]["next_action_count"], 2)
        self.assertTrue(result["client_delivery_summary"]["no_ai_token_used"])
        self.assertTrue(result["client_delivery_summary"]["no_browser_started"])
        self.assertTrue(result["client_delivery_summary"]["no_submit"])
        self.assertIn("最终交付还差证据：external_authorized_execution", result["reply"])
        self.assertTrue(any("24919,24922,24923" in row for row in result["next_actions"]))
        self.assertTrue(any("United States" in row for row in result["next_actions"]))
        self.assertEqual(result["final_delivery_evidence_plan"]["schema_version"], "reachops.final_delivery_evidence_plan.v1")
        self.assertTrue(result["no_ai_token_used"])

    def test_status_question_uses_final_status_delivery_boundary_without_tokens(self) -> None:
        runtime = {
            "run_session": {"state": "BLOCKED"},
            "run_result": {},
            "final_status": {
                "delivery_boundary": {
                    "schema_version": "reachops.delivery_boundary.v1",
                    "status": "local_capability_ready_final_pending",
                    "local_product_capability_ready": True,
                    "final_delivery_ready": False,
                    "external_validation_pending": True,
                },
                "product_capability_summary": {
                    "schema_version": "reachops.product_capability_summary.v1",
                    "ready": True,
                    "passed_count": 8,
                    "failed_count": 0,
                },
                "final_delivery_evidence_plan": {
                    "schema_version": "reachops.final_delivery_evidence_plan.v1",
                    "ready": False,
                    "pending_scopes": ["external_authorized_execution", "windows_final_artifacts"],
                    "items": [
                        {"scope": "external_authorized_execution", "next_action": "完成授权真实触达验收。"},
                        {"scope": "windows_final_artifacts", "next_action": "生成 Windows 最终包。"},
                    ],
                },
            },
        }

        result = self.console.handle("为什么停了", form=self.form, runtime=runtime)

        self.assertEqual(result["intent"], "explain_status")
        self.assertIn("交付边界：本地能力=true，最终交付=false", result["reply"])
        self.assertIn("产品能力矩阵：ready=true，failed=0", result["reply"])
        self.assertIn("最终交付还差证据：external_authorized_execution、windows_final_artifacts", result["reply"])
        self.assertEqual(result["evidence_bundle"]["delivery_boundary"]["status"], "local_capability_ready_final_pending")
        self.assertEqual(result["final_delivery_evidence_plan"]["schema_version"], "reachops.final_delivery_evidence_plan.v1")
        self.assertTrue(result["no_ai_token_used"])
        self.assertEqual(result["ai_usage_ledger"]["operator_console"]["token_estimate"], 0)

    def test_status_question_explains_operations_risk_gate_without_evidence_bundle(self) -> None:
        runtime = {
            "run_session": {"state": "BLOCKED"},
            "run_result": {},
            "operations": {
                "outreach_view": [
                    {
                        "target_username": "target_runtime_risk",
                        "action_type": "comment_reply",
                        "profile_id": "profile-risk-1",
                        "status": "skipped",
                        "error_code": "DUPLICATE_ACTION_TEXT",
                        "risk_gate_summary": "风险门禁阻断 / DUPLICATE_ACTION_TEXT / 类别：duplicate_text / 结果：blocked_rewrite_required",
                        "next_step": "改写或轮换话术后重试",
                    }
                ]
            },
        }

        result = self.console.handle("为什么不执行", form=self.form, runtime=runtime)

        self.assertEqual(result["intent"], "explain_status")
        self.assertIn("运营触达阻断", result["reply"])
        self.assertIn("DUPLICATE_ACTION_TEXT", result["reply"])
        self.assertIn("target_runtime_risk", result["reply"])
        self.assertEqual(result["operations_risk_gate_summary"]["blocked_count"], 1)
        self.assertIn("运营触达下一步：改写或轮换话术后重试", result["machine_actions"])
        self.assertEqual(result["operations_risk_gate_summary"]["no_ai_token_used"], True)
        self.assertEqual(result["ai_usage_ledger"]["execution_phase"]["token_estimate"], 0)

    def test_status_question_uses_operator_summary_and_evidence(self) -> None:
        runtime = {
            "run_session": {"state": "BLOCKED"},
            "run_result": {},
            "evidence_bundle": {
                "schema_version": "reachops.evidence_bundle.v1",
                "bundle_id": "bundle_status",
                "operator_summary": {
                    "schema_version": "reachops.operator_summary.v1",
                    "title": "执行需要处理",
                    "primary_blocker": "页面状态阻断执行。",
                    "next_actions": ["处理验证码后重新启动。"],
                    "no_ai_token_used": True,
                },
                "risk_summary": {
                    "schema_version": "reachops.risk_summary.v1",
                    "blocked_count": 1,
                    "authorization_block_count": 0,
                    "human_review_required_count": 1,
                    "block_execution_count": 1,
                    "risk_action_count": 2,
                    "decisions": [
                        {
                            "allowed": False,
                            "reason_code": "CAPTCHA_DETECTED",
                            "requires_human_review": True,
                            "block_execution": True,
                            "risk_actions": [
                                {"step": "block_execution", "required": True},
                                {"step": "cooldown_profile", "seconds": 3600},
                            ],
                        }
                    ],
                },
                "page_state_summary": {
                    "schema_version": "reachops.page_state_summary.v1",
                    "blocking_count": 1,
                    "unknown_count": 0,
                    "captcha_count": 1,
                },
                "repair_summary": {
                    "schema_version": "reachops.repair_summary.v1",
                    "block_count": 1,
                    "audit_events": [
                        {
                            "action": "cooldown_profile_and_switch",
                            "retry_after_seconds": 0,
                            "cooldown_seconds": 3600,
                            "requires_human_review": True,
                            "executable_steps": [
                                {"step": "capture_page_state_bundle", "required": True},
                                {"step": "switch_profile", "scope": "same_profile_group"},
                            ],
                        }
                    ],
                },
                "control_summary": {"schema_version": "reachops.control_summary.v1", "stop_count": 0},
                "timeline": [
                    {
                        "stage": "CHECKPOINT",
                        "source": "run_session.checkpoint",
                        "runtime_state_inferred": "REPAIRING",
                        "message": "repairing after captcha",
                        "no_ai_token_used": True,
                    },
                    {
                        "stage": "RISK_GATE",
                        "source": "risk_gate",
                        "allowed": False,
                        "reason_code": "CAPTCHA_DETECTED",
                        "profile_id": "profile-1",
                        "no_ai_token_used": True,
                    },
                    {
                        "stage": "PAGE_STATE",
                        "source": "page_state",
                        "state": "CAPTCHA_DETECTED",
                        "signals": ["captcha_or_verification_text"],
                        "no_ai_token_used": True,
                    },
                    {
                        "stage": "ACCOUNT_HEALTH",
                        "source": "runtime_log.account_health",
                        "profile_id": "profile-1",
                        "status": "cooldown",
                        "error_code": "COMMENT_SUBMIT_NOT_CONFIRMED",
                        "cooldown": True,
                        "no_ai_token_used": True,
                    },
                ],
            },
        }
        result = self.console.handle("为什么停了", form=self.form, runtime=runtime)
        self.assertEqual(result["intent"], "explain_status")
        self.assertIn("运营摘要：执行需要处理", result["reply"])
        self.assertIn("页面状态阻断执行", result["reply"])
        self.assertEqual(result["operator_summary"]["primary_blocker"], "页面状态阻断执行。")
        self.assertEqual(result["next_actions"][0], "处理验证码后重新启动。")
        self.assertEqual(result["evidence_bundle"]["page_state_summary"]["captcha_count"], 1)
        self.assertTrue(any("capture_page_state_bundle" in row for row in result["machine_actions"]))
        self.assertTrue(any("block_execution" in row for row in result["machine_actions"]))
        self.assertIn("本地机器动作", result["reply"])
        self.assertIn("时间线显示", result["reply"])
        self.assertTrue(any("风险门禁阻断：CAPTCHA_DETECTED" in row for row in result["timeline_summary"]))
        self.assertTrue(any("账号已进入冷却 profile=profile-1" in row for row in result["timeline_summary"]))
        self.assertEqual(result["evidence_bundle"]["timeline_summary"], result["timeline_summary"])

    def test_recap_uses_local_evidence_bundle_without_tokens(self) -> None:
        runtime = {
            "run_session": {"state": "BLOCKED"},
            "run_result": {"status": "failed"},
            "evidence_bundle": {
                "schema_version": "reachops.evidence_bundle.v1",
                "bundle_id": "bundle_test",
                "path": "/tmp/evidence.json",
                "markdown_path": "/tmp/evidence.md",
                "summary": {
                    "status": "blocked",
                    "state": "BLOCKED",
                    "target": "anti aging serum",
                    "mode": "collect",
                    "profile_group": "Canada",
                    "reason": "LOGIN_REQUIRED",
                    "blocked_or_degraded": True,
                    "no_ai_token_during_execution": True,
                },
                "operator_summary": {
                    "schema_version": "reachops.operator_summary.v1",
                    "title": "执行需要处理",
                    "severity": "blocked",
                    "primary_blocker": "真实动作缺少授权。",
                    "next_actions": ["补齐真实动作授权。"],
                    "no_ai_token_used": True,
                },
                "timeline": [
                    {"stage": "CREATED", "message": "RunSession created"},
                    {
                        "stage": "CHECKPOINT",
                        "source": "run_session.checkpoint",
                        "runtime_state_inferred": "BLOCKED",
                        "message": "blocked after authorization gate",
                        "no_ai_token_used": True,
                    },
                    {
                        "stage": "RISK_GATE",
                        "source": "risk_gate",
                        "allowed": False,
                        "reason_code": "LIVE_SUBMIT_NOT_AUTHORIZED",
                        "profile_id": "profile-1",
                        "no_ai_token_used": True,
                    },
                    {
                        "stage": "PAGE_STATE",
                        "source": "page_state",
                        "state": "CAPTCHA_DETECTED",
                        "signals": ["captcha_or_verification_text"],
                        "no_ai_token_used": True,
                    },
                ],
                "artifacts": [{"kind": "run_session", "exists": True}],
                "audit": {"no_ai_token_during_execution": True, "missing_artifacts": []},
                "repair_summary": {
                    "schema_version": "reachops.repair_summary.v1",
                    "decision_count": 1,
                    "retry_count": 1,
                    "switch_profile_count": 0,
                    "degrade_count": 0,
                    "block_count": 1,
                    "audit_events": [
                        {
                            "action": "retry_same_profile_with_backoff",
                            "retry_after_seconds": 5,
                            "requires_human_review": False,
                            "executable_steps": [
                                {"step": "capture_page_state_bundle", "required": True},
                                {"step": "backoff", "seconds": 5},
                                {"step": "retry_same_profile", "allowed": True},
                            ],
                        }
                    ],
                    "no_ai_token_used": True,
                },
                "risk_summary": {
                    "schema_version": "reachops.risk_summary.v1",
                    "decision_count": 1,
                    "allowed_count": 0,
                    "blocked_count": 1,
                    "authorization_block_count": 1,
                    "risk_action_count": 2,
                    "human_review_required_count": 1,
                    "block_execution_count": 1,
                    "decisions": [
                        {
                            "allowed": False,
                            "reason_code": "LIVE_SUBMIT_NOT_AUTHORIZED",
                            "requires_human_review": True,
                            "block_execution": True,
                            "risk_actions": [
                                {"step": "block_execution", "required": True},
                                {"step": "request_operator_authorization", "required": True},
                            ],
                        }
                    ],
                    "no_ai_token_used": True,
                },
                "risk_policy_summary": {
                    "schema_version": "reachops.risk_policy_summary.v1",
                    "policy_block_count": 3,
                    "quota_block_count": 1,
                    "rate_limit_block_count": 1,
                    "duplicate_text_block_count": 1,
                    "next_actions": ["更换触达话术或等待去重窗口结束。"],
                    "no_ai_token_used": True,
                },
                "operator_risk_gate_summary": {
                    "schema_version": "reachops.operator_risk_gate_summary.v1",
                    "row_count": 1,
                    "blocked_count": 1,
                    "allowed_count": 0,
                    "primary_reason": "风险门禁阻断 / LIVE_SUBMIT_NOT_AUTHORIZED",
                    "primary_next_step": "等待人工授权后再执行",
                    "rows": [
                        {
                            "target_username": "target-1",
                            "action_type": "comment_reply",
                            "profile_id": "profile-1",
                            "status": "skipped",
                            "risk_gate_summary": "风险门禁阻断 / LIVE_SUBMIT_NOT_AUTHORIZED",
                            "next_step": "等待人工授权后再执行",
                        }
                    ],
                    "no_ai_token_used": True,
                },
                "page_state_summary": {
                    "schema_version": "reachops.page_state_summary.v1",
                    "snapshot_count": 1,
                    "blocking_count": 1,
                    "unknown_count": 0,
                    "captcha_count": 1,
                    "state_counts": {"CAPTCHA_DETECTED": 1},
                    "no_ai_token_used": True,
                },
                "control_summary": {
                    "schema_version": "reachops.control_summary.v1",
                    "event_count": 1,
                    "pause_count": 0,
                    "resume_count": 0,
                    "stop_count": 1,
                    "recovery_count": 1,
                    "failed_control_count": 0,
                    "last_action": "stop",
                    "no_ai_token_used": True,
                },
                "run_recovery_summary": {
                    "schema_version": "reachops.run_recovery_summary.v1",
                    "recovered": True,
                    "recovery_count": 1,
                    "latest_reason": "PROCESS_INTERRUPTED",
                    "last_stage": "COLLECT profile=profile-1",
                    "runtime_state_inferred": "COLLECTING",
                    "checkpoint_log_line_count": 7,
                    "result_error": "process_interrupted",
                    "terminal_state": "BLOCKED",
                    "no_ai_token_used": True,
                },
                "ai_usage_summary": {
                    "schema_version": "reachops.ai_usage_summary.v1",
                    "audit_status": "pass",
                    "execution_phase_ai_call_count": 0,
                    "execution_phase_token_estimate": 0,
                    "no_ai_token_used": True,
                },
                "plan_runtime_contract": {
                    "schema_version": "reachops.plan_runtime_contract_summary.v1",
                    "contract_schema_version": "reachops.execution_plan_runtime_contract.v1",
                    "plan_id_matches": True,
                    "plan_fingerprint_matches": True,
                    "runtime_after_fingerprint_present": True,
                    "cli_args_ignored_for_plan_fields": True,
                    "no_ai_token_used": True,
                },
                "account_health_summary": {
                    "schema_version": "reachops.account_health_summary.v1",
                    "event_count": 2,
                    "cooldown_event_count": 1,
                    "no_ai_token_used": True,
                },
                "account_repair_summary": {
                    "schema_version": "reachops.account_repair_summary.v1",
                    "error_group_count": 1,
                    "hard_blocker_profile_count": 2,
                    "pending_recheck": True,
                    "manual_apply_required": True,
                    "operator_confirmed_apply": True,
                    "hard_blocker_only": True,
                    "no_browser_started": True,
                    "no_submit": True,
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
                    "no_ai_token_used": True,
                },
                "autonomy_readiness_summary": {
                    "schema_version": "reachops.autonomy_readiness_summary.v1",
                    "ready": True,
                    "passed_count": 9,
                    "failed_count": 0,
                    "no_ai_token_used": True,
                },
                "product_capability_summary": {
                    "schema_version": "reachops.product_capability_summary.v1",
                    "ready": True,
                    "passed_count": 8,
                    "failed_count": 0,
                    "phases": [
                        {
                            "phase": 3,
                            "key": "phase_3_autonomous_execution",
                            "title": "本地自治执行引擎",
                            "passed": True,
                        }
                    ],
                    "no_ai_token_used": True,
                },
                "autonomous_preflight_forecast": {
                    "schema_version": "reachops.autonomous_preflight_forecast_summary.v1",
                    "exists": True,
                    "source": "persisted_in_execution_plan",
                    "persisted": True,
                    "forecast_schema_version": "reachops.autonomous_preflight_forecast.v1",
                    "status": "ready",
                    "start_allowed": True,
                    "predicted_state_sequence": ["CREATED", "PRECHECK", "PROFILE_OPENING", "COLLECTING", "REPAIRING", "COMPLETED"],
                    "repair_route_count": 2,
                    "repair_routes": [
                        {"state": "LOGIN_REQUIRED", "action": "quarantine_profile"},
                        {"state": "UNKNOWN_PAGE_STATE", "action": "capture_error_bundle_then_block"},
                    ],
                    "evidence_requirement_count": 2,
                    "evidence_requirements": ["execution_plan_snapshot", "run_session_state_history"],
                    "runtime_invariants": {
                        "no_ai_token_during_execution": True,
                        "never_bypass_login_or_captcha": True,
                    },
                    "no_ai_token_used": True,
                },
                "autonomous_preflight_reconciliation": {
                    "schema_version": "reachops.autonomous_preflight_reconciliation.v1",
                    "forecast_exists": True,
                    "forecast_source": "persisted_in_execution_plan",
                    "forecast_persisted": True,
                    "status": "partially_matched",
                    "actual_page_states": ["CAPTCHA_DETECTED"],
                    "actual_page_state_counts": {"CAPTCHA_DETECTED": 1},
                    "actual_repair_actions": ["capture_page_state_bundle", "retry_same_profile_with_backoff"],
                    "actual_risk_reasons": ["LIVE_SUBMIT_NOT_AUTHORIZED"],
                    "actual_risk_actions": ["block_execution", "request_operator_authorization"],
                    "matched_route_count": 1,
                    "matched_routes": [
                        {
                            "state": "CAPTCHA_DETECTED",
                            "action": "capture_page_state_bundle",
                            "terminal_outcome": "blocked",
                            "match_reasons": ["page_state_observed", "repair_action_observed"],
                        }
                    ],
                    "unobserved_route_count": 1,
                    "unobserved_routes": [
                        {"state": "UNKNOWN_PAGE_STATE", "action": "capture_error_bundle_then_block"}
                    ],
                    "risk_gate_aligned": True,
                    "no_ai_token_used": True,
                },
                "offline_learning": {"record_count": 0},
            },
        }
        result = self.console.handle("复盘这次执行", form=self.form, runtime=runtime)
        self.assertEqual(result["intent"], "run_recap")
        self.assertTrue(result["no_ai_token_used"])
        self.assertEqual(result["run_session_state"], "BLOCKED")
        self.assertIn("LOGIN_REQUIRED", result["reply"])
        self.assertIn("运营摘要：执行需要处理", result["reply"])
        self.assertIn("真实动作缺少授权", result["reply"])
        self.assertIn("关键时间线：风险门禁阻断：LIVE_SUBMIT_NOT_AUTHORIZED", result["reply"])
        self.assertIn("未消耗 AI token", result["reply"])
        self.assertIn("自修复记录：1 个决策", result["reply"])
        self.assertIn("风险门禁：1 个决策", result["reply"])
        self.assertIn("2 个风险动作", result["reply"])
        self.assertIn("风险策略：3 个策略阻断", result["reply"])
        self.assertIn("1 个额度阻断", result["reply"])
        self.assertIn("1 个重复话术阻断", result["reply"])
        self.assertIn("运营风险门禁：1 条记录", result["reply"])
        self.assertIn("主原因=风险门禁阻断 / LIVE_SUBMIT_NOT_AUTHORIZED", result["reply"])
        self.assertIn("下一步=等待人工授权后再执行", result["reply"])
        self.assertIn("机器动作摘要", result["reply"])
        self.assertIn("页面状态：1 个快照", result["reply"])
        self.assertIn("运行控制：1 个事件", result["reply"])
        self.assertIn("中断恢复：recovered=true", result["reply"])
        self.assertIn("reason=PROCESS_INTERRUPTED", result["reply"])
        self.assertIn("账号健康：2 个事件", result["reply"])
        self.assertIn("账号修复：1 个错误分组", result["reply"])
        self.assertIn("待重新预检=true", result["reply"])
        self.assertIn("账号修复安全边界", result["reply"])
        self.assertIn("manual_apply_required=true", result["reply"])
        self.assertIn("hard_blocker_only=true", result["reply"])
        self.assertIn("no_browser_started=true", result["reply"])
        self.assertIn("no_submit=true", result["reply"])
        self.assertIn("no_ai_token_used=true", result["reply"])
        self.assertIn("计划运行合同：plan_id_match=true", result["reply"])
        self.assertIn("fingerprint_match=true", result["reply"])
        self.assertIn("runtime_fingerprint=true", result["reply"])
        self.assertIn("启动前预判：exists=true", result["reply"])
        self.assertIn("source=persisted_in_execution_plan", result["reply"])
        self.assertIn("repair_routes=2", result["reply"])
        self.assertIn("预判对账：status=partially_matched", result["reply"])
        self.assertIn("matched=1", result["reply"])
        self.assertIn("执行期 AI 调用：0 次", result["reply"])
        self.assertIn("自治链路：ready=true", result["reply"])
        self.assertIn("产品能力矩阵：ready=true", result["reply"])
        self.assertTrue(any("backoff" in row for row in result["machine_actions"]))
        self.assertTrue(any("request_operator_authorization" in row for row in result["machine_actions"]))
        self.assertTrue(any("证据包运营下一步：等待人工授权后再执行" in row for row in result["machine_actions"]))
        self.assertTrue(any("启动前自治预判" in row for row in result["machine_actions"]))
        self.assertTrue(any("source=persisted_in_execution_plan" in row for row in result["machine_actions"]))
        self.assertTrue(any("UNKNOWN_PAGE_STATE:capture_error_bundle_then_block" in row for row in result["machine_actions"]))
        self.assertTrue(any("预判对账" in row for row in result["machine_actions"]))
        self.assertTrue(any("中断恢复" in row for row in result["machine_actions"]))
        self.assertTrue(any("账号修复安全边界" in row for row in result["machine_actions"]))
        self.assertTrue(any("不打开浏览器" in row for row in result["machine_actions"]))
        self.assertTrue(any("不提交平台动作" in row for row in result["machine_actions"]))
        self.assertTrue(any("CAPTCHA_DETECTED" in row for row in result["machine_actions"]))
        self.assertEqual(result["evidence_bundle"]["repair_summary"]["decision_count"], 1)
        self.assertEqual(result["evidence_bundle"]["risk_summary"]["blocked_count"], 1)
        self.assertEqual(result["evidence_bundle"]["risk_policy_summary"]["duplicate_text_block_count"], 1)
        self.assertEqual(result["evidence_bundle"]["operator_risk_gate_summary"]["blocked_count"], 1)
        self.assertTrue(any("更换触达话术" in row for row in result["next_actions"]))
        self.assertEqual(result["evidence_bundle"]["page_state_summary"]["captcha_count"], 1)
        self.assertEqual(result["evidence_bundle"]["control_summary"]["stop_count"], 1)
        self.assertTrue(result["evidence_bundle"]["run_recovery_summary"]["recovered"])
        self.assertEqual(result["evidence_bundle"]["ai_usage_summary"]["execution_phase_token_estimate"], 0)
        self.assertTrue(result["evidence_bundle"]["plan_runtime_contract"]["plan_id_matches"])
        self.assertEqual(result["evidence_bundle"]["account_health_summary"]["cooldown_event_count"], 1)
        self.assertEqual(result["evidence_bundle"]["account_repair_summary"]["hard_blocker_profile_count"], 2)
        self.assertTrue(result["evidence_bundle"]["autonomy_readiness_summary"]["ready"])
        self.assertTrue(result["evidence_bundle"]["autonomous_preflight_forecast"]["exists"])
        self.assertEqual(
            result["evidence_bundle"]["autonomous_preflight_reconciliation"]["schema_version"],
            "reachops.autonomous_preflight_reconciliation.v1",
        )
        self.assertEqual(result["evidence_bundle"]["autonomous_preflight_reconciliation"]["matched_route_count"], 1)
        self.assertTrue(result["evidence_bundle"]["product_capability_summary"]["ready"])
        self.assertEqual(result["evidence_bundle"]["product_capability_summary"]["passed_count"], 8)
        self.assertTrue(any("重新预检" in row for row in result["next_actions"]))
        self.assertTrue(any("人工确认隔离硬阻断账号" in row for row in result["next_actions"]))
        self.assertEqual(result["evidence_bundle"]["operator_summary"]["severity"], "blocked")
        self.assertEqual(result["evidence_bundle"]["bundle_id"], "bundle_test")
        self.assertEqual(result["evidence_bundle"]["summary"]["status"], "blocked")
        self.assertTrue(any("页面状态：CAPTCHA_DETECTED" in row for row in result["timeline_summary"]))
        self.assertTrue(any("预判状态链：CREATED" in row for row in result["timeline_summary"]))
        self.assertEqual(result["evidence_bundle"]["timeline_summary"], result["timeline_summary"])

    def test_unknown_state_analysis_uses_offline_learning_without_tokens(self) -> None:
        runtime = {
            "offline_learning": {
                "schema_version": "reachops.offline_learning.v1",
                "ledger_path": "/tmp/unknown_states.json",
                "record_count": 1,
                "records": [
                    {
                        "signature": "uls_test",
                        "state": "UNKNOWN_PAGE_STATE",
                        "occurrence_count": 3,
                        "evidence_paths": ["/tmp/unknown-1.png"],
                        "suggested_policy": {
                            "candidate_state": "CAPTCHA_DETECTED",
                            "candidate_action": "cooldown_profile_and_switch",
                            "confidence": "medium",
                        },
                    }
                ],
                "policy_candidates": {
                    "schema_version": "reachops.offline_policy_candidates.v1",
                    "candidate_count": 1,
                    "min_occurrences": 2,
                    "candidates": [
                        {
                            "candidate_state": "CAPTCHA_DETECTED",
                            "candidate_action": "cooldown_profile_and_switch",
                            "occurrence_count": 3,
                            "evidence_paths": ["/tmp/unknown-1.png", "/tmp/unknown-2.png"],
                            "requires_human_review": True,
                            "auto_apply": False,
                        }
                    ],
                    "no_ai_token_used": True,
                },
                "policy_review_summary": {
                    "schema_version": "reachops.offline_policy_review.v1",
                    "review_count": 1,
                    "approved_count": 1,
                    "rejected_count": 0,
                    "runtime_auto_apply_count": 0,
                    "no_ai_token_used": True,
                },
                "policy_release_proposal": {
                    "schema_version": "reachops.offline_policy_release_proposal.v1",
                    "approved_count": 1,
                    "ready_for_release_count": 1,
                    "release_gate": "code_or_policy_release_required",
                    "runtime_auto_apply_count": 0,
                    "runtime_auto_apply": False,
                    "proposals": [],
                    "no_ai_token_used": True,
                },
                "no_ai_token_used": True,
            }
        }
        result = self.console.handle("分析未知错误", form=self.form, runtime=runtime)
        self.assertEqual(result["intent"], "unknown_state_analysis")
        self.assertTrue(result["no_ai_token_used"])
        self.assertEqual(result["offline_learning"]["record_count"], 1)
        self.assertEqual(result["offline_learning"]["policy_candidates"]["candidate_count"], 1)
        self.assertEqual(result["offline_learning"]["evidence_path_count"], 2)
        self.assertIn("/tmp/unknown-2.png", result["offline_learning"]["evidence_paths"])
        self.assertIn("CAPTCHA_DETECTED", result["reply"])
        self.assertIn("可核对证据文件 2 个", result["reply"])
        self.assertTrue(any("2 个未知状态证据文件" in row for row in result["next_actions"]))
        self.assertIn("候选规则", result["reply"])
        self.assertEqual(
            result["offline_learning"]["policy_release_proposal"]["schema_version"],
            "reachops.offline_policy_release_proposal.v1",
        )
        self.assertEqual(result["offline_learning"]["policy_release_proposal"]["ready_for_release_count"], 1)
        self.assertEqual(result["offline_learning"]["policy_release_proposal"]["runtime_auto_apply_count"], 0)
        self.assertIn("策略发布建议", result["reply"])
        self.assertIn("runtime_auto_apply=0", result["reply"])
        self.assertIn("不会自动绕过 RiskGate", result["reply"])

    def test_unknown_state_analysis_handles_empty_ledger(self) -> None:
        result = self.console.handle("分析未知页面状态", form=self.form, runtime={"offline_learning": {"record_count": 0, "records": []}})
        self.assertEqual(result["intent"], "unknown_state_analysis")
        self.assertIn("没有未知状态离线学习记录", result["reply"])
        self.assertTrue(result["no_ai_token_used"])


if __name__ == "__main__":
    unittest.main()

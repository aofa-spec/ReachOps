# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from ReachOps.execution_plan import build_execution_plan
from ReachOps.run_recovery import recover_interrupted_run_session, should_recover_interrupted_run
from ReachOps.run_session import (
    build_session_health,
    create_run_session,
    infer_run_state,
    is_allowed_state_transition,
    transition_run_session,
)


class RunRecoveryTests(unittest.TestCase):
    def test_running_session_without_process_recovers_to_blocked(self) -> None:
        plan = build_execution_plan(target="anti aging serum", mode="collect")
        session = create_run_session(plan, execution_plan_path="/tmp/plan.json", result_path="/tmp/result.json", log_path="/tmp/log.txt")
        session = transition_run_session(session, "COLLECTING", pid=1234, last_stage="COLLECT running")
        session = transition_run_session(
            session,
            "COLLECTING",
            pid=1234,
            control={"paused": True, "last_action": "pause", "status": "paused", "ok": True, "reason": "test_pause"},
        )
        self.assertEqual(session["control_history"][-1]["action"], "pause")
        self.assertTrue(session["control"]["current_paused"])
        session = transition_run_session(
            session,
            "COLLECTING",
            pid=1234,
            control={"paused": True},
        )
        self.assertEqual(len(session["control_history"]), 1)
        self.assertEqual(session["control"]["last_action"], "pause")
        self.assertTrue(session["control"]["current_paused"])
        self.assertTrue(should_recover_interrupted_run(session, running=False, run_result={}))
        updated, recovery = recover_interrupted_run_session(session, running=False, run_result={}, last_stage="last line")
        self.assertTrue(recovery["recovered"])
        self.assertEqual(updated["state"], "BLOCKED")
        self.assertEqual(updated["result"]["error"], "process_interrupted")
        self.assertEqual(updated["result"]["recovery"]["reason"], "PROCESS_INTERRUPTED")
        self.assertEqual(updated["control_history"][-1]["action"], "recover_interrupted_run")
        self.assertEqual(updated["control_history"][-1]["reason"], "PROCESS_INTERRUPTED")
        self.assertTrue(updated["no_ai_token_during_execution"])
        self.assertEqual(updated["ai_usage_ledger"]["schema_version"], "reachops.ai_usage_ledger.v1")
        self.assertEqual(updated["ai_usage_ledger"]["execution_phase"]["ai_call_count"], 0)
        self.assertEqual(updated["ai_usage_ledger"]["execution_phase"]["token_estimate"], 0)
        self.assertEqual(updated["ai_usage_ledger"]["audit_status"], "pass")
        self.assertEqual(updated["execution_runtime_contract"]["schema_version"], "reachops.execution_runtime_contract.v1")
        self.assertEqual(updated["execution_runtime_contract"]["executor"], "local_program")
        self.assertFalse(updated["execution_runtime_contract"]["ai_console_is_execution_dependency"])
        self.assertFalse(updated["ai_usage_ledger"]["policy"]["execution_phase_ai_calls_allowed"])
        self.assertEqual(updated["ai_usage_ledger"]["policy"]["executor"], "local_program")
        self.assertFalse(updated["ai_usage_ledger"]["policy"]["ai_console_is_execution_dependency"])

    def test_terminal_session_does_not_recover(self) -> None:
        plan = build_execution_plan(target="anti aging serum")
        session = create_run_session(plan)
        session = transition_run_session(session, "COMPLETED", result={"status": "completed"})
        updated, recovery = recover_interrupted_run_session(session, running=False, run_result={"status": "completed"})
        self.assertFalse(recovery["recovered"])
        self.assertEqual(updated["state"], "COMPLETED")

    def test_infer_run_state_treats_blocked_campaign_log_as_blocked(self) -> None:
        state = infer_run_state(
            [
                "CHECK  profile_preflight checked=9 available=0",
                "BLOCK  campaign failed reason=无可用账号 error=INSUFFICIENT_LOGGED_IN_PROFILES",
            ],
            running=False,
            run_result={},
        )

        self.assertEqual(state, "BLOCKED")

    def test_checkpoint_update_records_runtime_evidence(self) -> None:
        plan = build_execution_plan(target="anti aging serum", mode="collect")
        session = create_run_session(plan)
        session = transition_run_session(
            session,
            "SCORING",
            last_stage="SCORE candidate_user_scored",
            checkpoint_update={
                "runtime_state_inferred": "SCORING",
                "log_line_count": 12,
                "last_log_line": "SCORE candidate_user_scored creator=abc",
                "terminal_seen": False,
                "no_ai_token_used": True,
            },
        )
        self.assertEqual(session["state"], "SCORING")
        self.assertEqual(session["checkpoint"]["runtime_state_inferred"], "SCORING")
        self.assertEqual(session["checkpoint"]["log_line_count"], 12)
        self.assertEqual(session["checkpoint"]["last_log_line"], "SCORE candidate_user_scored creator=abc")
        self.assertFalse(session["checkpoint"]["terminal_seen"])
        self.assertTrue(session["checkpoint"]["no_ai_token_used"])
        self.assertEqual(session["session_health"]["status"], "healthy")
        self.assertEqual(session["session_health"]["last_stage"], "SCORE candidate_user_scored")
        self.assertTrue(any(row["state"] == "CREATED" for row in session["state_history"]))
        self.assertEqual(session["state_history"][-1]["state"], "SCORING")
        self.assertTrue(all(row.get("no_ai_token_used") is True for row in session["state_history"]))

    def test_state_history_dedupes_identical_transitions(self) -> None:
        plan = build_execution_plan(target="anti aging serum", mode="collect")
        session = create_run_session(plan)
        session = transition_run_session(session, "PRECHECK", last_stage="RUN web_headless_start")
        self.assertTrue(session["state_machine_contract"]["valid_transition"])
        self.assertEqual(session["state_transition_violations"], [])
        self.assertEqual(session["state_history"][-1]["from_state"], "CREATED")
        self.assertEqual(session["state_history"][-1]["to_state"], "PRECHECK")
        count = len(session["state_history"])
        session = transition_run_session(session, "PRECHECK", last_stage="RUN web_headless_start")
        self.assertEqual(len(session["state_history"]), count)
        session = transition_run_session(
            session,
            "PRECHECK",
            last_stage="RUN web_headless_start",
            checkpoint_update={"log_line_count": 2, "runtime_state_inferred": "PRECHECK"},
        )
        self.assertEqual(len(session["state_history"]), count + 1)

    def test_state_machine_contract_records_invalid_transition_without_tokens(self) -> None:
        plan = build_execution_plan(target="anti aging serum", mode="collect")
        session = create_run_session(plan)
        self.assertTrue(is_allowed_state_transition("CREATED", "PRECHECK"))
        self.assertFalse(is_allowed_state_transition("CREATED", "EXECUTING"))
        session = transition_run_session(session, "EXECUTING", last_stage="invalid direct execution")
        self.assertFalse(session["state_machine_contract"]["valid_transition"])
        self.assertEqual(session["state_machine_contract"]["violation_count"], 1)
        self.assertEqual(session["state_transition_violations"][0]["from_state"], "CREATED")
        self.assertEqual(session["state_transition_violations"][0]["to_state"], "EXECUTING")
        self.assertEqual(session["state_history"][-1]["violation"], "invalid_state_transition")
        self.assertTrue(session["state_history"][-1]["no_ai_token_used"])

    def test_session_health_detects_stale_paused_and_terminal_states(self) -> None:
        plan = build_execution_plan(target="anti aging serum", mode="collect")
        session = create_run_session(plan)
        session = transition_run_session(session, "COLLECTING", last_stage="COLLECT running")
        session["updated_at"] = "2026-01-01T00:00:00Z"
        stale = build_session_health(session, running=True, stale_after_seconds=1)
        self.assertEqual(stale["status"], "stale")
        self.assertTrue(stale["stale"])

        paused_session = transition_run_session(
            session,
            "COLLECTING",
            control={"paused": True, "last_action": "pause", "status": "paused", "ok": True},
        )
        paused = build_session_health(paused_session, running=True, stale_after_seconds=1)
        self.assertEqual(paused["status"], "paused")
        self.assertFalse(paused["stale"])

        terminal_session = transition_run_session(session, "BLOCKED", result={"status": "blocked"})
        terminal = build_session_health(terminal_session, running=False, stale_after_seconds=1)
        self.assertEqual(terminal["status"], "terminal")
        self.assertTrue(terminal["terminal"])

    def test_result_execution_plan_contract_is_indexed_in_evidence(self) -> None:
        plan = build_execution_plan(target="anti aging serum", mode="collect")
        session = create_run_session(plan, execution_plan_path="/tmp/plan.json")
        self.assertEqual(session["execution_runtime_contract"]["schema_version"], "reachops.execution_runtime_contract.v1")
        self.assertEqual(session["evidence"]["execution_runtime_contract"]["schema_version"], "reachops.execution_runtime_contract.v1")
        self.assertFalse(session["ai_usage_ledger"]["policy"]["execution_phase_ai_calls_allowed"])
        contract = {
            "schema_version": "reachops.execution_plan_runtime_contract.v1",
            "source": "execution_plan",
            "plan_id": plan["plan_id"],
            "cli_args_ignored_for_plan_fields": True,
            "no_ai_token_used": True,
        }
        session = transition_run_session(
            session,
            "COMPLETED",
            result={"status": "completed", "execution_plan_contract": contract},
        )
        self.assertEqual(
            session["evidence"]["execution_plan_contract"]["schema_version"],
            "reachops.execution_plan_runtime_contract.v1",
        )
        self.assertTrue(session["evidence"]["execution_plan_contract"]["cli_args_ignored_for_plan_fields"])
        self.assertEqual(session["result"]["execution_plan_contract"]["plan_id"], plan["plan_id"])

    def test_infer_run_state_identifies_execution_phase(self) -> None:
        self.assertEqual(
            infer_run_state(
                [
                    "START  web_ui_start_request target_present=true group=Canada "
                    "mode=preflight account_repair_confirmed=false"
                ],
                running=True,
            ),
            "PRECHECK",
        )
        self.assertEqual(
            infer_run_state(["ACTION action_queue_created"], running=True),
            "ACTION_PLANNING",
        )
        self.assertEqual(
            infer_run_state(["WARN   web_ui_account_gate_blocked group=Canada"], running=True),
            "REPAIRING",
        )
        self.assertEqual(
            infer_run_state(["DONE   action_preflight batch=123"], running=True),
            "EXECUTING",
        )
        self.assertEqual(
            infer_run_state(["DONE   action_submit batch=123"], running=True),
            "EXECUTING",
        )


if __name__ == "__main__":
    unittest.main()

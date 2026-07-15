import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

from ReachOps.execution_plan import build_execution_plan
from tools.run_reachops_headless_macos import apply_execution_plan_to_args, classify_headless_terminal_status, main


class HeadlessExecutionPlanContractTests(unittest.TestCase):
    def test_execution_plan_overrides_conflicting_cli_runtime_fields(self):
        args = argparse.Namespace(
            base_dir="cli-base",
            target="cli target",
            source_type="auto",
            profile_group="CLI Group",
            profile_limit=99,
            max_videos=99,
            max_comments=99,
            mode="live_comment",
            volume="stress",
            comment_text="cli comment",
            timeout=999,
        )
        plan = build_execution_plan(
            target="plan target",
            source_type="keyword",
            mode="collect",
            profile_group="Plan Group",
            volume="quick",
            profile_limit=3,
            max_videos=4,
            max_comments=5,
            timeout_seconds=60,
            comment_text="plan comment",
            base_dir="plan-base",
            origin="unit_test",
        )

        contract = apply_execution_plan_to_args(args, plan)

        self.assertEqual(contract["schema_version"], "reachops.execution_plan_runtime_contract.v1")
        self.assertEqual(contract["source"], "execution_plan")
        self.assertEqual(contract["plan_fingerprint_sha256"], plan["plan_fingerprint_sha256"])
        self.assertTrue(contract["runtime_after_fingerprint_sha256"])
        self.assertTrue(contract["cli_args_ignored_for_plan_fields"])
        self.assertEqual(contract["before"]["target"], "cli target")
        self.assertEqual(contract["after"]["target"], "plan target")
        self.assertEqual(args.source_type, "keyword")
        self.assertEqual(args.profile_group, "Plan Group")
        self.assertEqual(args.mode, "collect")
        self.assertEqual(args.volume, "quick")
        self.assertEqual(args.profile_limit, 3)
        self.assertEqual(args.max_videos, 4)
        self.assertEqual(args.max_comments, 5)
        self.assertEqual(args.timeout, 60)
        self.assertEqual(args.comment_text, "plan comment")
        self.assertEqual(args.base_dir, "plan-base")
        self.assertTrue(contract["no_ai_token_used"])

    def test_headless_cli_without_plan_synthesizes_execution_plan_before_running(self):
        with tempfile.TemporaryDirectory() as td:
            argv = [
                "run_reachops_headless_macos.py",
                "--base-dir",
                td,
                "--target",
                "anti aging serum",
                "--source-type",
                "keyword",
                "--profile-group",
                "Canada",
                "--mode",
                "collect",
                "--profile-limit",
                "2",
                "--max-videos",
                "4",
                "--max-comments",
                "5",
                "--timeout",
                "30",
                "--json",
            ]
            output = io.StringIO()
            with redirect_stdout(output), patch("sys.argv", argv), patch(
                "tools.run_reachops_headless_macos.check_ixbrowser_start_gate",
                return_value={
                    "ready": False,
                    "error": "IXBROWSER_LOCAL_API_UNAVAILABLE",
                    "message": "offline in unit test",
                    "no_browser_started": True,
                    "no_submit": True,
                },
            ):
                code = main()

            self.assertEqual(code, 2)
            latest_plan = Path(td) / "plans" / "latest_execution_plan.json"
            self.assertTrue(latest_plan.is_file())
            text = latest_plan.read_text(encoding="utf-8")
            self.assertIn('"schema_version": "reachops.execution_plan.v1"', text)
            self.assertIn('"target": "anti aging serum"', text)
            result = json.loads(output.getvalue())
            contract = result["execution_plan_contract"]
            self.assertEqual(result["execution_plan"]["source"], "cli_synthesized_execution_plan")
            self.assertEqual(contract["source"], "cli_synthesized_execution_plan")
            self.assertEqual(contract["schema_version"], "reachops.execution_plan_runtime_contract.v1")
            self.assertTrue(contract["cli_args_ignored_for_plan_fields"])
            self.assertEqual(contract["after"]["target"], "anti aging serum")
            self.assertEqual(contract["after"]["profile_group"], "Canada")
            self.assertEqual(contract["after"]["mode"], "collect")
            self.assertEqual(contract["after"]["profile_limit"], 2)
            self.assertTrue(contract["runtime_after_fingerprint_sha256"])
            self.assertTrue(contract["no_ai_token_used"])
            run_session_path = Path(result["run_session"]["path"])
            self.assertTrue(run_session_path.is_file())
            self.assertEqual(run_session_path.parent, Path(td) / "runs")
            latest_run_session = Path(td) / "runs" / "latest_run_session.json"
            self.assertTrue(latest_run_session.is_file())
            run_session = json.loads(latest_run_session.read_text(encoding="utf-8"))
            self.assertEqual(run_session["schema_version"], "reachops.run_session.v1")
            self.assertEqual(run_session["state"], "BLOCKED")
            self.assertEqual(run_session["evidence"]["execution_plan_contract"]["source"], "cli_synthesized_execution_plan")
            self.assertTrue(run_session["no_ai_token_during_execution"])
            self.assertTrue(run_session["ai_usage_ledger"]["no_ai_token_used"])
            result_files = sorted((Path(td) / "run_results").glob("*.json"))
            self.assertTrue(result_files)

    def test_headless_blocked_campaign_terminal_is_not_completed(self):
        lines = [
            "2026-07-15 15:32:03  CHECK  profile_preflight checked=9 available=0 unavailable=9 errors=PAGE_OPEN_FAILED=3, PROFILE_PREFLIGHT_TIMEOUT=6",
            "2026-07-15 15:32:03  BLOCK  campaign failed reason=无可用账号 required=1 available=0 checked=9 auto_limit=24 error=INSUFFICIENT_LOGGED_IN_PROFILES next=补充已登录可用账号",
        ]

        status = classify_headless_terminal_status(lines, timed_out=False)

        self.assertEqual(status["status"], "blocked_by_accounts")
        self.assertEqual(status["run_session_state"], "BLOCKED")
        self.assertEqual(status["exit_code"], 2)
        self.assertEqual(status["error_code"], "BLOCKED_BY_ACCOUNTS")

    def test_headless_done_terminal_remains_completed(self):
        status = classify_headless_terminal_status(
            [
                "2026-07-15 15:20:01  DONE   collection batch=gb_ok",
                "2026-07-15 15:20:02  DONE   action_preflight queued=0 no_submit=true",
            ],
            timed_out=False,
        )

        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["run_session_state"], "COMPLETED")
        self.assertEqual(status["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()

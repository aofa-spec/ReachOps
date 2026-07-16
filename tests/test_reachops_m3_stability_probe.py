import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import reachops_m3_stability_probe as m3


def completed_payload(run_id: str = "run_1", status: str = "passed", scenario_status: str = "ok") -> dict:
    return {
        "run_id": run_id,
        "report_path": f"/tmp/{run_id}/reachops_mac_real_flow_report.json",
        "no_submit": True,
        "selected_profile_ids": ["18444", "18979", "18981"],
        "usable_profile_ids": ["18444", "18979", "18981"] if status == "passed" else [],
        "blocked_profile_ids": [] if status == "passed" else ["18444", "18979", "18981"],
        "profile_launch_budget": {"daily_counts": {"18444": 1, "18979": 1, "18981": 1}},
        "acceptance": {"status": status, "no_submit": True},
        "scenarios": [
            {
                "status": scenario_status,
                "diagnosis_status": "duplicate_suppressed" if status == "passed" else "no_logged_in_profile_available",
                "browser_started": 1 if status == "passed" else 0,
                "profile_preflight": {
                    "skipped": False,
                    "checked": 3,
                    "available": 3 if status == "passed" else 0,
                    "unavailable": 0 if status == "passed" else 3,
                },
                "funnel": {
                    "target_sources": 1,
                    "content_found": 0,
                    "comment_users": 0,
                    "customer_leads": 0,
                    "outreach_actions": 0,
                },
                "no_action_reason": {"code": "duplicate_suppressed", "no_submit": True},
            }
        ],
    }


def payload_with_pool(
    run_id: str,
    *,
    status: str = "passed",
    usable_profile_ids: list[str] | None = None,
    blocked_profile_ids: list[str] | None = None,
) -> dict:
    usable_profile_ids = usable_profile_ids if usable_profile_ids is not None else ["18444", "18979", "18981"]
    blocked_profile_ids = blocked_profile_ids if blocked_profile_ids is not None else []
    payload = completed_payload(run_id, status=status)
    payload["selected_profile_ids"] = ["18444", "18979", "18981"]
    payload["usable_profile_ids"] = usable_profile_ids
    payload["blocked_profile_ids"] = blocked_profile_ids
    payload["acceptance"] = {"status": status, "no_submit": True}
    payload["scenarios"][0]["profile_preflight"] = {
        "skipped": False,
        "checked": len(usable_profile_ids) + len(blocked_profile_ids),
        "available": len(usable_profile_ids),
        "unavailable": len(blocked_profile_ids),
    }
    payload["scenarios"][0]["browser_started"] = len(usable_profile_ids)
    return payload


def completed_process(payload: dict, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["python"], returncode=returncode, stdout=json.dumps(payload), stderr="")


class ReachOpsM3StabilityProbeTest(unittest.TestCase):
    def base_args(self, tmpdir: str, iterations: int = 2):
        return m3.parse_args(
            [
                "--target",
                "https://www.tiktok.com/@ayieinaussie/photo/7646939533241601301",
                "--profile-group",
                "获客分组测试",
                "--profile-ids",
                "18444,18979,18981",
                "--iterations",
                str(iterations),
                "--output-dir",
                str(Path(tmpdir) / "m3_probe"),
                "--cooldown-seconds",
                "0",
                "--quiet",
                "--json",
            ]
        )

    def test_m3_probe_completes_when_all_iterations_pass(self):
        with TemporaryDirectory() as tmpdir:
            args = self.base_args(tmpdir, iterations=2)
            runs = [
                completed_process(completed_payload("run_1")),
                completed_process(completed_payload("run_2")),
            ]
            with patch("tools.reachops_m3_stability_probe.subprocess.run", side_effect=runs) as run_mock:
                code, summary = m3.run_probe(args)

            summary_path = Path(summary["summary_path"])
            written = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(summary["terminal_state"], "COMPLETED")
        self.assertEqual(summary["passed_count"], 2)
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(written["schema_version"], "reachops.m3_probe_summary.v1")
        command = run_mock.call_args_list[0].args[0]
        self.assertEqual(command[4:6], ["--profile-ids", "18444,18979,18981"])
        self.assertIn("--max-attempt-batches", command)
        self.assertIn("1", command)
        self.assertIn("--json", command)

    def test_m3_probe_stops_on_first_failed_iteration(self):
        with TemporaryDirectory() as tmpdir:
            args = self.base_args(tmpdir, iterations=20)
            runs = [
                completed_process(completed_payload("run_1")),
                completed_process(completed_payload("run_2", status="blocked", scenario_status="failed"), returncode=2),
                completed_process(completed_payload("run_3")),
            ]
            with patch("tools.reachops_m3_stability_probe.subprocess.run", side_effect=runs) as run_mock:
                code, summary = m3.run_probe(args)

        self.assertEqual(code, 2)
        self.assertEqual(summary["terminal_state"], "BLOCKED")
        self.assertEqual(summary["iterations_completed"], 2)
        self.assertEqual(summary["passed_count"], 1)
        self.assertEqual(summary["failed_count"], 1)
        self.assertEqual(summary["rows"][-1]["diagnosis_status"], "no_logged_in_profile_available")
        self.assertEqual(run_mock.call_count, 2)

    def test_m3_probe_converts_iteration_timeout_to_blocked_summary(self):
        with TemporaryDirectory() as tmpdir:
            args = self.base_args(tmpdir, iterations=20)
            with patch(
                "tools.reachops_m3_stability_probe.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=1, output="", stderr=""),
            ) as run_mock:
                code, summary = m3.run_probe(args)

        self.assertEqual(code, 2)
        self.assertEqual(summary["terminal_state"], "BLOCKED")
        self.assertEqual(summary["iterations_completed"], 1)
        self.assertEqual(summary["failed_count"], 1)
        self.assertEqual(summary["rows"][0]["returncode"], 2)
        self.assertIn("iteration_timeout", summary["rows"][0]["stderr_tail"])
        self.assertEqual(run_mock.call_count, 1)

    def test_m3_probe_waits_between_successful_iterations_when_configured(self):
        with TemporaryDirectory() as tmpdir:
            args = self.base_args(tmpdir, iterations=2)
            args.cooldown_seconds = 7
            runs = [
                completed_process(completed_payload("run_1")),
                completed_process(completed_payload("run_2")),
            ]
            with patch("tools.reachops_m3_stability_probe.subprocess.run", side_effect=runs), patch(
                "tools.reachops_m3_stability_probe.time.sleep"
            ) as sleep_mock:
                code, summary = m3.run_probe(args)

        self.assertEqual(code, 0)
        self.assertEqual(summary["terminal_state"], "COMPLETED")
        self.assertEqual(summary["cooldown_seconds"], 7)
        sleep_mock.assert_called_once_with(7)

    def test_m3_probe_excludes_blocked_profiles_between_iterations(self):
        with TemporaryDirectory() as tmpdir:
            args = self.base_args(tmpdir, iterations=20)
            args.profile_ids = "18444,18979,18981,13708"
            args.profile_limit = 4
            args.profile_scan_limit = 4
            runs = [
                completed_process(
                    payload_with_pool(
                        "run_1",
                        usable_profile_ids=["18444", "13708"],
                        blocked_profile_ids=["18979", "18981"],
                    )
                ),
                completed_process(completed_payload("run_2")),
            ]
            with patch("tools.reachops_m3_stability_probe.subprocess.run", side_effect=runs) as run_mock:
                code, summary = m3.run_probe(args)

        self.assertEqual(code, 2)
        self.assertEqual(summary["terminal_state"], "BLOCKED")
        self.assertEqual(summary["terminal_reason"], "insufficient_active_profiles_for_m3")
        self.assertEqual(summary["iterations_completed"], 1)
        self.assertEqual(summary["active_profile_ids"], ["18444", "13708"])
        self.assertEqual(summary["excluded_profile_ids"], ["18979", "18981"])
        self.assertEqual(run_mock.call_count, 1)

    def test_m3_probe_can_delegate_profile_selection_to_group_runtime(self):
        with TemporaryDirectory() as tmpdir:
            args = m3.parse_args(
                [
                    "--target",
                    "https://www.tiktok.com/@ayieinaussie/photo/7646939533241601301",
                    "--profile-group",
                    "获客分组测试",
                    "--iterations",
                    "1",
                    "--output-dir",
                    str(Path(tmpdir) / "m3_probe"),
                    "--quiet",
                    "--json",
                ]
            )
            with patch(
                "tools.reachops_m3_stability_probe.subprocess.run",
                return_value=completed_process(completed_payload("run_1")),
            ) as run_mock:
                code, summary = m3.run_probe(args)

        self.assertEqual(code, 0)
        self.assertEqual(summary["terminal_state"], "COMPLETED")
        command = run_mock.call_args_list[0].args[0]
        self.assertNotIn("--profile-ids", command)
        self.assertEqual(summary["profile_ids"], [])

    def test_m3_probe_requires_three_profiles_by_default(self):
        args = m3.parse_args(
            [
                "--target",
                "https://www.tiktok.com/@ayieinaussie/photo/7646939533241601301",
                "--profile-ids",
                "18444,18979",
                "--quiet",
                "--json",
            ]
        )

        code, summary = m3.run_probe(args)

        self.assertEqual(code, 2)
        self.assertEqual(summary["terminal_state"], "BLOCKED")
        self.assertEqual(summary["terminal_reason"], "insufficient_profile_ids_for_m3")
        self.assertEqual(summary["iterations_completed"], 0)


if __name__ == "__main__":
    unittest.main()

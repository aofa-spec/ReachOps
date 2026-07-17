from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one anchor in {path}, found {count}:\n{old[:500]}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_action_router() -> None:
    path = ROOT / "ReachOps/workbench/action_router.py"
    replace_once(
        path,
        '''    def _assert_executor_contract(self, config: ActionRouterConfig) -> None:
        if self._execution_mode(config) == "live" and isinstance(self.executor, FixtureActionExecutor):
            raise RuntimeError("LIVE_EXECUTOR_REQUIRED: live execution cannot use FixtureActionExecutor")
''',
        '''    def _assert_executor_contract(self, config: ActionRouterConfig) -> None:
        if self._execution_mode(config) != "live" or not isinstance(self.executor, FixtureActionExecutor):
            return
        test_fixture_enabled = str(os.environ.get("REACHOPS_ALLOW_TEST_FIXTURE_LIVE") or "").strip() == "1"
        if not test_fixture_enabled:
            raise RuntimeError("LIVE_EXECUTOR_REQUIRED: live execution cannot use FixtureActionExecutor")
        self.storage.log_event(
            "live_fixture_test_override_enabled",
            "",
            {
                "test_only": True,
                "execution_mode": "live",
                "counts_require_real_evidence": True,
            },
        )
''',
    )


def patch_legacy_tests() -> None:
    path = ROOT / "tests/test_reachops_campaign.py"
    replace_once(
        path,
        '''            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "success" for row in new_actions))
''',
        '''            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "pending_review" for row in new_actions))
            truth = service.storage.outreach_execution_truth_counts(new_batch["id"])
            self.assertEqual(truth["simulated_success"], 1)
            self.assertEqual(truth["live_verified"], 0)
''',
    )
    replace_once(
        path,
        '''            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "success" for row in old_actions))
            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "pending_review" for row in new_actions))
''',
        '''            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "pending_review" for row in old_actions))
            self.assertTrue(any(row["action_type"] == "comment_reply" and row["status"] == "pending_review" for row in new_actions))
            truth = service.storage.outreach_execution_truth_counts(old_batch["id"])
            self.assertEqual(truth["simulated_success"], 1)
            self.assertEqual(truth["live_verified"], 0)
''',
    )
    replace_once(
        path,
        '''            self.assertEqual(old_funnel["execution_success"], 1)
            self.assertEqual(old_funnel["preflight_ok"], 1)
''',
        '''            self.assertEqual(old_funnel["execution_success"], 0)
            self.assertEqual(old_funnel["preflight_ok"], 0)
            truth = service.storage.outreach_execution_truth_counts(old_batch["id"])
            self.assertEqual(truth["simulated_success"], 1)
            self.assertEqual(truth["live_verified"], 0)
''',
    )
    replace_once(
        path,
        '''            self.assertEqual(fallback["batch_id"], batch["id"])
            self.assertEqual(fallback["status"], "success")
''',
        '''            self.assertEqual(fallback["batch_id"], batch["id"])
            self.assertEqual(fallback["status"], "pending_review")
            self.assertEqual(fallback["suggested_text"], "")
            truth = service.storage.outreach_execution_truth_counts(batch["id"])
            self.assertGreaterEqual(truth["simulated_success"], 1)
            self.assertEqual(truth["live_verified"], 0)
''',
    )


def patch_operator_pressure() -> None:
    path = ROOT / "tools/reachops_operator_pressure.py"
    replace_once(
        path,
        '''    if int(final_funnel.get("execution_success") or 0) < 1:
        failures.append("final_funnel_execution_missing")
''',
        '''    if int(final_funnel.get("execution_success") or 0) != 0:
        failures.append("final_funnel_live_success_must_remain_zero")
''',
    )


def main() -> None:
    patch_action_router()
    patch_legacy_tests()
    patch_operator_pressure()
    print("truthful execution compatibility patch applied")


if __name__ == "__main__":
    main()
